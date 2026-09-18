"""Recoverable preset management. Never opens model data or changes audio code."""
import base64
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

RETENTION_DAYS = 30


def _json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("プリセット管理ファイルの形式が不正です: " + path.name)
    return value


def _bytes(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".library-tmp")
    with temporary.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(path))


def _inside(root, path):
    """Reject escaping paths and links/junctions, including parent components."""
    root = Path(root).absolute()
    path = Path(os.path.abspath(str(path)))
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise ValueError("アプリの外にあるファイルは変更できません。")
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            info = cursor.lstat()
            if cursor.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("リンク先のファイルは変更できません。")
    return path


def _path(root, relative):
    return _inside(root, Path(root) / relative)


def _relative(root, path):
    return _inside(root, path).relative_to(Path(root).absolute()).as_posix()


def _identity(path, root):
    from configs.model_presets import model_identity
    return model_identity(path, str(root))


def _same(a, b, root):
    return bool(a and b and _identity(a, root) == _identity(b, root))


def _registry(root):
    value = _json(_path(root, "configs/preset_library.json"), {"schema_version": 1, "deleted": {}})
    if not isinstance(value.get("deleted"), dict):
        raise ValueError("プリセットの削除履歴を読み取れません。")
    return value


def is_deleted(pth_path, app_root):
    if not pth_path:
        return False
    return _identity(pth_path, app_root) in _registry(app_root)["deleted"]


@contextmanager
def _locked(root):
    path = _path(root, "configs/preset_library.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if not path.stat().st_size:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        import msvcrt
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise OSError("別のプリセット操作が実行中です。少し待って再試行してください。")
        try:
            _recover(root)
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _recover(root):
    journal_path = _path(root, "configs/preset_transaction.json")
    journal = _json(journal_path)
    if journal.get("state") != "pending":
        return
    # Writes are rolled back before moves, in reverse operation order.
    for record in reversed(journal["writes"]):
        path = _path(root, record["path"])
        before = base64.b64decode(record["before"]) if record["before"] is not None else None
        after = base64.b64decode(record["after"])
        current = path.read_bytes() if path.exists() else None
        if current is None and any(move["dst"] == record["path"] for move in journal["moves"]):
            continue  # Its preceding move did not happen yet.
        if current not in (before, after):
            raise OSError("復旧対象が外部で変更されています。上書きせず停止しました: " + path.name)
        if current == before:
            continue
        if before is None:
            holding = _path(root, "configs/preset_recovery/" + uuid.uuid4().hex + ".json")
            holding.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(path), str(holding))
        else:
            _atomic(path, before)
    for record in reversed(journal["moves"]):
        src, dst = _path(root, record["src"]), _path(root, record["dst"])
        if dst.exists() and not src.exists():
            info = dst.stat()
            correct = (hashlib.sha256(dst.read_bytes()).hexdigest() == record["sha256"]
                       if record.get("sha256") else
                       [info.st_dev, info.st_ino, info.st_size] == record["identity"])
            if not correct:
                raise OSError("移動先が外部で変更されています。復旧を停止しました。")
            src.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(dst), str(src))
        elif src.exists() and dst.exists():
            raise OSError("復旧先に同名ファイルがあります。上書きせず停止しました。")
    _atomic(journal_path, _bytes({"state": "rolled_back"}))


def _transaction(root, moves=(), writes=None):
    """Journal metadata bytes and move identities before doing any mutation."""
    writes = writes or {}
    records, virtual = [], {}
    for src, dst in moves:
        src, dst = _inside(root, src), _inside(root, dst)
        key = os.path.normcase(str(src))
        content = virtual.get(key)
        if content is None:
            info = src.stat()
            content = ([info.st_dev, info.st_ino, info.st_size],
                       src.read_bytes() if src.suffix.lower() == ".json" else None)
        if dst.exists() and os.path.normcase(str(dst)) not in {
                os.path.normcase(str(a)) for a, _ in moves}:
            raise FileExistsError("同名ファイルが存在します: " + dst.name)
        virtual[os.path.normcase(str(dst))] = content
        records.append({"src": _relative(root, src), "dst": _relative(root, dst), "identity": content[0],
                        "sha256": hashlib.sha256(content[1]).hexdigest() if content[1] is not None else None})
    changes = []
    for path, data in writes.items():
        path = _inside(root, path)
        moved = virtual.get(os.path.normcase(str(path)))
        before = moved[1] if moved is not None else (path.read_bytes() if path.exists() else None)
        changes.append({"path": _relative(root, path),
                        "before": base64.b64encode(before).decode() if before is not None else None,
                        "after": base64.b64encode(_bytes(data)).decode()})
    journal = _path(root, "configs/preset_transaction.json")
    _atomic(journal, _bytes({"state": "pending", "moves": records, "writes": changes}))
    try:
        for record in records:
            src, dst = _path(root, record["src"]), _path(root, record["dst"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(src), str(dst))
        for change in changes:
            _atomic(_path(root, change["path"]), base64.b64decode(change["after"]))
        _atomic(journal, _bytes({"state": "committed"}))
    except Exception:
        _recover(root)
        raise


def recover_library(app_root):
    with _locked(Path(app_root).absolute()):
        pass


def allow_reimport(app_root, pth_path):
    """Expired records may be re-added explicitly, never by automatic saving."""
    root = Path(app_root).absolute()
    with _locked(root):
        registry = _registry(root)
        identity = _identity(pth_path, root)
        entry_id = registry["deleted"].get(identity)
        if not entry_id:
            return
        if _path(root, "configs/preset_trash/" + entry_id + "/manifest.json").exists():
            raise ValueError("このモデルはアプリ内のゴミ箱にあります。ゴミ箱から復元してください。")
        registry["deleted"].pop(identity)
        _transaction(root, writes={root / "configs/preset_library.json": registry})


def _active_presets(root):
    directory = _path(root, "configs/model_presets")
    result = []
    for path in sorted(directory.glob("*.json")):
        _inside(root, path)
        # Fail closed: do not rename files while some references are unreadable.
        result.append((path, _json(path)))
    return result


def _entries(root):
    directory = _path(root, "configs/preset_trash")
    result = []
    for folder in sorted(directory.glob("*")):
        if not re.fullmatch(r"[0-9a-f]{32}", folder.name):
            continue
        manifest = _path(root, _relative(root, folder / "manifest.json"))
        if not manifest.exists():
            continue
        data = _json(manifest)
        if data.get("status") == "deleted":
            result.append((folder, data))
    return result


def list_deleted(app_root, now=None):
    now = now or datetime.now(timezone.utc)
    result = []
    for folder, data in _entries(Path(app_root).absolute()):
        row = dict(data, id=folder.name)
        row["remaining_days"] = max(0, int((datetime.fromisoformat(data["expires_at"]) - now).total_seconds() + 86399) // 86400)
        result.append(row)
    return sorted(result, key=lambda row: row["deleted_at"], reverse=True)


def delete_preset(app_root, pth_path, now=None):
    root = Path(app_root).absolute()
    now = now or datetime.now(timezone.utc)
    with _locked(root):
        registry = _registry(root)
        identity = _identity(pth_path, root)
        if identity in registry["deleted"]:
            raise ValueError("このプリセットはすでに削除されています。")
        selected = [(p, d) for p, d in _active_presets(root) if _same(d.get("pth_path"), pth_path, root)]
        if not selected:
            raise ValueError("削除するプリセットが見つかりません。")
        entry_id = uuid.uuid4().hex
        folder = _path(root, "configs/preset_trash/" + entry_id)
        from configs.model_presets import portable_path, model_name_from_path
        files = [{"original": _relative(root, p), "stored": "presets/" + p.name} for p, _ in selected]
        manifest = {"schema_version": 1, "status": "deleted", "model_name": model_name_from_path(pth_path),
                    "pth_path": portable_path(pth_path, str(root)), "model_identity": identity,
                    "deleted_at": now.isoformat(), "expires_at": (now + timedelta(days=RETENTION_DAYS)).isoformat(),
                    "files": files}
        registry["deleted"][identity] = entry_id
        writes = {folder / "manifest.json": manifest, root / "configs/preset_library.json": registry}
        session_path = _path(root, "configs/inuse/config.json")
        session = _json(session_path)
        if _same(session.get("pth_path"), pth_path, root):
            session.update(pth_path="", index_path="")
            writes[session_path] = session
        moves = [(p, folder / f["stored"]) for (p, _), f in zip(selected, files)]
        _transaction(root, moves, writes)
        return entry_id


def restore_preset(app_root, entry_id):
    root = Path(app_root).absolute()
    if not re.fullmatch(r"[0-9a-f]{32}", entry_id):
        raise ValueError("無効な復元対象です。")
    with _locked(root):
        folder = _path(root, "configs/preset_trash/" + entry_id)
        manifest = _json(folder / "manifest.json")
        if manifest.get("status") != "deleted":
            raise ValueError("復元するプリセットがありません。")
        if not (root / manifest["pth_path"]).is_file():
            raise ValueError("元のモデルファイルが見つかりません。元の場所に戻してから復元してください。")
        moves = []
        for file in manifest["files"]:
            src = _inside(folder, folder / file["stored"])
            dst = _path(root, file["original"])
            if dst.parent != root / "configs/model_presets" or dst.suffix != ".json":
                raise ValueError("復元先がプリセットフォルダではありません。")
            if dst.exists():
                raise FileExistsError("復元先に同名設定があります。上書きせず停止しました。")
            moves.append((src, dst))
        registry = _registry(root)
        if registry["deleted"].get(manifest["model_identity"]) != entry_id:
            raise ValueError("削除履歴が一致しないため復元を停止しました。")
        registry["deleted"].pop(manifest["model_identity"])
        manifest["status"] = "restored"
        _transaction(root, moves, {root / "configs/preset_library.json": registry, folder / "manifest.json": manifest})
        return str(root / manifest["pth_path"])


def _new_name(name, suffix):
    name = str(name).strip()
    if name.lower().endswith(suffix):
        name = name[:-len(suffix)]
    if (not name or name[-1:] in (".", " ") or len(name) > 100
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.match(r"^(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\.|$)", name, re.I)):
        raise ValueError("ファイル名に使えない文字・予約名です。拡張子を除く100文字以内で入力してください。")
    return name + suffix


def rename_file(app_root, pth_path, kind, name):
    from configs.model_presets import _read_preset, portable_path, preset_path_for_model
    root = Path(app_root).absolute()
    if kind not in ("model", "index"):
        raise ValueError("無効なリネーム対象です。")
    with _locked(root):
        preset = _read_preset(pth_path, str(root))
        if preset is None or is_deleted(pth_path, root):
            raise ValueError("操作するプリセットが見つかりません。")
        key, suffix = ("pth_path", ".pth") if kind == "model" else ("index_path", ".index")
        value = pth_path if kind == "model" else preset.get(key, "")
        if not value:
            raise ValueError("Indexが設定されていません。")
        src = _path(root, value)
        allowed = [root / "assets/weights"] if kind == "model" else [root / "assets/indices", root / "logs"]
        if not any(src == folder / src.name or folder in src.parents for folder in allowed):
            raise ValueError("アプリに取り込んだモデル・Indexのみ名前を変更できます。")
        if not src.is_file() or src.suffix.lower() != suffix:
            raise ValueError("対象ファイルが見つかりません。")
        dst = src.with_name(_new_name(name, suffix))
        if str(src) == str(dst):
            return str(src), str(dst)
        case_only = os.path.normcase(str(src)) == os.path.normcase(str(dst))
        if dst.exists() and not case_only:
            raise FileExistsError("同名ファイルが存在します。別の名前を指定してください。")
        stage = src.with_name(".__preset_rename_" + uuid.uuid4().hex + suffix)
        moves = [(src, stage), (stage, dst)] if case_only else [(src, dst)]
        writes = {}
        canonical_old = Path(preset_path_for_model(str(src), str(root)))
        matching = [(p, d) for p, d in _active_presets(root) if _same(d.get(key), str(src), root)]
        canonical_source = next((p for p, _ in matching if p == canonical_old), matching[0][0] if matching else None)

        def update(data):
            if not _same(data.get(key), str(src), root):
                return False
            data[key] = portable_path(str(dst), str(root))
            if kind == "model":
                data.update(model_identity=_identity(str(dst), root), model_name=dst.stem)
            return True

        for path, data in matching:
            update(data)
            target = path
            if kind == "model" and path == canonical_source:
                target = Path(preset_path_for_model(str(dst), str(root)))
                if target != path:
                    if target.exists():
                        raise FileExistsError("同名のプリセット設定が存在します。")
                    moves.append((path, target))
            writes[target] = data
        for folder, manifest in _entries(root):
            for file in manifest["files"]:
                path = _inside(folder, folder / file["stored"])
                data = _json(path)
                if update(data):
                    writes[path] = data
        session_path = _path(root, "configs/inuse/config.json")
        session = _json(session_path)
        if _same(session.get(key), str(src), root):
            session[key] = portable_path(str(dst), str(root))
            writes[session_path] = session
        if kind == "model" and _identity(str(dst), root) in _registry(root)["deleted"]:
            raise ValueError("その名前の削除履歴があります。先に復元するか、別の名前を指定してください。")
        _transaction(root, moves, writes)
        return str(src), str(dst)


def _recycle(folder):
    """Windows Recycle Bin only; never fall back to permanent deletion."""
    script = ("param([string]$Target)\nAdd-Type -AssemblyName Microsoft.VisualBasic\n"
              "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($Target,"
              "[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,"
              "[Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin,"
              "[Microsoft.VisualBasic.FileIO.UICancelOption]::ThrowException)")
    # Pass the literal path as data, not interpolated PowerShell code.
    encoded_path = base64.b64encode(str(folder).encode("utf-8")).decode("ascii")
    command = "$Target=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s')); " % encoded_path
    command += script.split("\n", 1)[1]
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    result = subprocess.run([os.path.join(os.environ["SystemRoot"], "System32/WindowsPowerShell/v1.0/powershell.exe"),
                             "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
    if result.returncode or folder.exists():
        raise OSError("Windowsのゴミ箱へ移せなかったため、復元用データを保持しています。")


def expire_deleted(app_root, now=None, recycle=None):
    root = Path(app_root).absolute()
    now = now or datetime.now(timezone.utc)
    moved, errors = [], []
    with _locked(root):
        for folder, data in _entries(root):
            if datetime.fromisoformat(data["expires_at"]) > now:
                continue
            # Only this app's recorded metadata files may be recycled, never assets.
            expected = {"manifest.json"} | {f["stored"] for f in data["files"]}
            actual = set()
            for path in folder.rglob("*"):
                _inside(root, path)
                if path.is_file():
                    actual.add(path.relative_to(folder).as_posix())
            if actual != expected or any(not p.endswith(".json") for p in actual):
                errors.append("復元用フォルダに想定外のファイルがあります。自動移動を中止しました。")
                continue
            try:
                (recycle or _recycle)(folder)
                moved.append(folder.name)
            except (OSError, subprocess.TimeoutExpired) as error:
                errors.append(str(error))
    return moved, errors
