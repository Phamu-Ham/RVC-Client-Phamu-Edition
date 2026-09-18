"""Bounded, redacted support logs. No audio, model loading, or network access."""
import atexit
import datetime as dt
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import queue
import re
import stat
import sys
import threading
import traceback
import uuid
import zipfile

MAX_BYTES = 2 * 1024 * 1024
KEEP_LOGS = 8
LOG_NAME = re.compile(r"client-\d{8}-\d{6}-[0-9a-f]{8}\.log\Z")
INSTALL_NAME = re.compile(r"installer-\d{8}-\d{9}-[0-9a-f]{8}\.log\Z")
_session = None


def safe_path(path):
    """Reject symlinks/junctions before opening or recycling diagnostic files."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise OSError("Diagnostic paths must not use links")
    return path


class Redactor:
    def __init__(self, app_root):
        self.roots = [str(Path(app_root).absolute())]
        self.identities = [v for v in (os.environ.get("USERNAME"), os.environ.get("COMPUTERNAME"))
                           if v and len(v) >= 3]

    def __call__(self, text):
        text = str(text)
        for root in self.roots:
            for spelling in (root.replace("\\", "\\\\"), root, root.replace("\\", "/")):
                text = re.sub(re.escape(spelling), "<APP>", text, flags=re.I)
        # Whole external paths (including spaces) are deliberately over-redacted.
        text = re.sub(r"(?i)https?://[^\s\"'<>]+", "<URL>", text)
        text = re.sub(r'(?i)"(?:[a-z]:[\\/]|\\\\)[^"\r\n]*"', '"<PATH>"', text)
        text = re.sub(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n\"'<>|]*", "<PATH>", text)
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<EMAIL>", text)
        text = re.sub(r'(?i)("(?:token|password|secret|api[_-]?key|authorization)"\s*:\s*)"[^"\r\n]*"',
                      r'\1"<REDACTED>"', text)
        text = re.sub(r"(?i)\b(token|password|secret|api[_-]?key|authorization)\b\s*[:=]\s*[^\r\n]+",
                      r"\1=<REDACTED>", text)
        for identity in self.identities:
            text = re.sub(r"(?<!\w)" + re.escape(identity) + r"(?!\w)", "<USER>", text, flags=re.I)
        return text


def recycle_file(path):
    """Recycle one verified log, never recursively delete a directory."""
    path = safe_path(path)
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class Operation(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.WORD), ("aborted", wintypes.BOOL),
                    ("mapping", ctypes.c_void_p), ("title", wintypes.LPCWSTR)]
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHFileOperationW.argtypes = [ctypes.POINTER(Operation)]
    shell.SHFileOperationW.restype = ctypes.c_int
    operation = Operation(None, 3, str(path) + "\0", None, 0x40 | 0x10 | 0x400 | 0x4,
                          False, None, None)
    return shell.SHFileOperationW(ctypes.byref(operation)) == 0 and not operation.aborted


class Session:
    def __init__(self, app_root, directory=None, limit=MAX_BYTES):
        self.redact = Redactor(app_root)
        self.directory = safe_path(directory or Path(app_root) / "support_logs")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / ("client-%s-%s.log" %
                    (dt.datetime.now().strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:8]))
        self.handle = self.path.open("xb")
        self.limit, self.size, self.capped = limit, 0, False
        self.failed = False
        self.messages = queue.Queue(maxsize=512)
        self.lock = threading.Lock()
        self.closed = False
        self.dropped = 0
        self.worker = threading.Thread(target=self._run, name="support-log", daemon=True)
        self.worker.start()

    def record(self, message):
        if self.closed or self.capped or self.failed:
            return
        try:
            self.messages.put_nowait(str(message)[:16000])
        except queue.Full:
            self.dropped += 1

    def _run(self):
        while True:
            item = self.messages.get()
            try:
                if item is None:
                    return
                prefix = dt.datetime.now().isoformat(timespec="seconds")
                data = ("[%s] %s\n" % (prefix, self.redact(item))).encode("utf-8", "replace")
                with self.lock:
                    if not self.capped and not self.failed:
                        if self.size + len(data) > self.limit - 128:
                            data = b"[support] Log size limit reached; further messages omitted.\n"
                            self.capped = True
                        try:
                            self.handle.write(data)
                            self.handle.flush()
                            self.size += len(data)
                        except (OSError, ValueError):
                            self.failed = True  # Diagnostics must never terminate the client.
            finally:
                self.messages.task_done()

    def flush(self):
        self.messages.join()

    def prune(self, recycle=recycle_file):
        files = sorted((p for p in self.directory.iterdir()
                        if p != self.path and LOG_NAME.fullmatch(p.name)),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for path in files[KEEP_LOGS - 1:]:
            try:
                if path != self.path and safe_path(path).is_file():
                    recycle(path)
            except OSError:
                pass  # Locked/inaccessible logs remain recoverable, never force-delete.

    def close(self):
        if self.closed:
            return
        self.record("Log session ended; dropped messages: %d" % self.dropped)
        self.closed = True
        self.messages.put(None)
        self.worker.join(timeout=2)
        if not self.worker.is_alive():
            self.handle.close()


class Tee:
    """Queue complete lines so split print() writes cannot bypass redaction."""
    def __init__(self, original, session, label):
        self.original, self.session, self.label = original, session, label
        self.pending = ""
        self.discard = False
        self.lock = threading.Lock()

    def write(self, text):
        if self.original is not None:
            try:
                self.original.write(text)
            except (OSError, UnicodeError):
                pass
        with self.lock:
            for piece in str(text).splitlines(keepends=True):
                if not self.discard:
                    self.pending += piece
                    if len(self.pending) > 16000:
                        self.pending = "[oversized line omitted]"
                        self.discard = True
                if piece.endswith(("\n", "\r")):
                    self.session.record(self.label + ": " + self.pending.rstrip())
                    self.pending, self.discard = "", False
        return len(text)

    def flush(self):
        if self.original is not None:
            try:
                self.original.flush()
            except OSError:
                pass

    def finish(self):
        with self.lock:
            if self.pending:
                self.session.record(self.label + ": " + self.pending)
                self.pending = ""

    def __getattr__(self, name):
        return getattr(self.original, name)


def environment_info():
    data = {"system": platform.system(), "release": platform.release(),
            "windows_version": platform.version(), "architecture": platform.machine(),
            "python": platform.python_version(), "packages": {}}
    data["log_status"] = ({"write_failed": _session.failed, "size_capped": _session.capped,
                           "dropped_messages": _session.dropped} if _session else {"active": False})
    for package in ("torch", "torchaudio", "numpy", "sounddevice", "PySimpleGUI", "faiss-cpu"):
        try:
            data["packages"][package] = importlib.metadata.version(package)
        except (importlib.metadata.PackageNotFoundError, OSError, ValueError):
            data["packages"][package] = "not installed"
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            data["cuda_build"] = getattr(torch.version, "cuda", None)
            # Only use cached GPU properties: diagnostics must not initialize CUDA.
            if torch.cuda.is_initialized():
                data["gpu"] = torch.cuda.get_device_name()
        except Exception as error:
            data["gpu_query_error"] = type(error).__name__
    return data


def record(message):
    if _session is not None:
        _session.record(message)


def install(app_root):
    global _session
    if _session is not None:
        return _session
    fallback = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PhamuStudio/RVCClient/support_logs"
    for directory in (Path(app_root) / "support_logs", fallback):
        try:
            _session = Session(app_root, directory)
            break
        except OSError:
            continue
    if _session is None:
        print("ログを保存できません。画面のエラー内容を控えてください。", flush=True)
        return None
    stdout, stderr = Tee(sys.stdout, _session, "stdout"), Tee(sys.stderr, _session, "stderr")
    sys.stdout, sys.stderr = stdout, stderr
    previous = sys.excepthook

    def exception_hook(kind, value, tb):
        record("Unhandled exception\n" + "".join(traceback.format_exception(kind, value, tb)))
        _session.flush()
        previous(kind, value, tb)
    sys.excepthook = exception_hook
    if hasattr(threading, "excepthook"):
        previous_thread = threading.excepthook

        def thread_hook(args):
            record("Worker exception\n" + "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback)))
            previous_thread(args)
        threading.excepthook = thread_hook

    def close():
        stdout.finish()
        stderr.finish()
        _session.close()
    atexit.register(close)
    try:
        _session.prune()
    except OSError:
        record("Older logs could not be recycled; they were kept")
    print("問い合わせ用ログ: " + str(_session.path), flush=True)
    record("Environment: " + json.dumps(environment_info(), ensure_ascii=False))
    return _session


def attach_tk(root):
    def tk_exception(kind, value, tb):
        record("GUI callback exception\n" + "".join(traceback.format_exception(kind, value, tb)))
        traceback.print_exception(kind, value, tb)
    root.report_callback_exception = tk_exception


def export_bundle(app_root, destination, audio=None):
    """Allowlist text logs only; never walk model/config/audio directories."""
    if _session is not None:
        _session.flush()
    root = Path(app_root)
    redact = Redactor(root)
    folders = [(root / "support_logs", LOG_NAME, "client")]
    if _session is not None and _session.directory != folders[0][0]:
        folders.append((_session.directory, LOG_NAME, "fallback"))
    # The installer BAT is beside the installed root, two levels above 本体.
    if root.name == "本体":
        folders.append((root.parent.parent / "Phamu-Installer-Logs", INSTALL_NAME, "installer"))
    destination = safe_path(destination)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for directory, pattern, label in folders:
            try:
                safe_path(directory)
                paths = sorted((p for p in directory.iterdir() if pattern.fullmatch(p.name)), reverse=True)[:KEEP_LOGS]
            except OSError:
                continue
            for path in paths:
                try:
                    safe_path(path)
                    with path.open("rb") as handle:
                        data = handle.read(MAX_BYTES).decode("utf-8", "replace")
                    archive.writestr(label + "/" + path.name, redact(data))
                except OSError:
                    continue
        info = environment_info()
        if audio:
            allowed = ("host_api", "sample_rate", "channels", "block_seconds", "f0_method",
                       "pitch", "index_rate", "input_channels", "output_channels")
            info["audio"] = {k: v for k, v in audio.items() if k in allowed and isinstance(v, (str, int, float, bool))}
        archive.writestr("environment.json", redact(json.dumps(info, ensure_ascii=False, indent=2)))
        archive.writestr("README.txt", "問い合わせ用ログです。自動送信はしていません。\n"
                         "音声・モデル・画像・設定ファイルは含みません。\n"
                         "パス等は自動伏せ字化していますが、送信前に内容を確認してください。\n"
                         "過去の logs/realtime_gui_error.log は個人パスを含み得るため収録しません。\n")
    return destination
