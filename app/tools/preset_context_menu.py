"""Frameless themed popup; no native Windows Menu border or window hooks."""
import ctypes
from ctypes import wintypes
import sys
import tkinter as tk
from tkinter import font as tkfont

from tools.yozakura_theme import YOZAKURA, YOZAKURA_FONT


def _work_area(root, x, y):
    if sys.platform == "win32":
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        # Function signatures must not leak into the main window's Win32 calls.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return info.work.left, info.work.top, info.work.right, info.work.bottom
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def _place_and_round(window, x, y, width, height, place=True):
    if sys.platform != "win32":
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
    gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    # Absolute screen coordinates also work on monitors left/above the primary.
    if place:
        user32.SetWindowPos(hwnd, None, x, y, width, height, 0x0004 | 0x0010)
    region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, 16, 16)
    if region and not user32.SetWindowRgn(hwnd, region, True):
        gdi32.DeleteObject(region)


class PresetContextMenu:
    """The small Menu API used by the gallery, with explicit popup lifetime."""
    def __init__(self, root):
        self.root = root
        self.entries = []
        self.window = None
        self.rows = {}
        self.active = None
        self.previous_focus = None

    def add_command(self, label, state="normal", command=None):
        self.entries.append(dict(label=label, state=state, command=command))

    def add_separator(self):
        self.entries.append(None)

    def entrycget(self, index, option):
        return self.entries[index][option]

    def invoke(self, index):
        item = self.entries[index]
        if item is None or item["state"] == "disabled":
            return
        callback = item["command"]
        self.destroy()
        if callback:
            callback()

    def _activate(self, index):
        item = self.entries[index]
        if item is None or item["state"] == "disabled":
            return
        self.active = index
        for key, button in self.rows.items():
            selected = key == index
            button.configure(background=YOZAKURA["pink"] if selected else YOZAKURA["card_alt"],
                             foreground=YOZAKURA["bg"] if selected else
                             YOZAKURA["muted"] if self.entries[key]["state"] == "disabled" else YOZAKURA["text"])

    def _step(self, direction):
        available = [i for i, item in enumerate(self.entries) if item and item["state"] != "disabled"]
        if available:
            position = available.index(self.active) if self.active in available else (-1 if direction > 0 else 0)
            self._activate(available[(position + direction) % len(available)])
        return "break"

    def _outside(self, event):
        if self.window is None:
            return
        win = self.window
        if not (win.winfo_rootx() <= event.x_root < win.winfo_rootx() + win.winfo_width()
                and win.winfo_rooty() <= event.y_root < win.winfo_rooty() + win.winfo_height()):
            self.destroy()
            return "break"

    def _focus_out(self, _event):
        if self.window is not None:
            self.window.after_idle(self._check_focus)

    def _check_focus(self):
        if self.window is None:
            return
        try:
            focused = self.window.focus_displayof()
            if focused is None or focused.winfo_toplevel() is not self.window:
                self.destroy(restore_focus=False)
        except tk.TclError:
            self.destroy(restore_focus=False)

    def tk_popup(self, x, y):
        self.destroy()
        self.previous_focus = self.root.focus_get()
        win = self.window = tk.Toplevel(self.root, background=YOZAKURA["border"], bd=0, highlightthickness=0)
        win.withdraw()
        win.overrideredirect(True)
        win.transient(self.root)
        win.attributes("-topmost", True)
        content = tk.Frame(win, bg=YOZAKURA["card_alt"], bd=0, padx=5, pady=5)
        content.pack(fill="both", expand=True, padx=1, pady=1)
        font = tkfont.Font(root=self.root, family=YOZAKURA_FONT, size=10)
        width = max(font.measure(item["label"]) for item in self.entries if item) + 40
        for index, item in enumerate(self.entries):
            if item is None:
                tk.Frame(content, height=1, bg=YOZAKURA["border"]).pack(fill="x", padx=8, pady=5)
                continue
            button = tk.Button(content, text=item["label"], anchor="w", font=font,
                               bg=YOZAKURA["card_alt"], fg=YOZAKURA["text"],
                               activebackground=YOZAKURA["pink"], activeforeground=YOZAKURA["bg"],
                               disabledforeground=YOZAKURA["muted"], state=item["state"],
                               relief="flat", bd=0, highlightthickness=0, padx=10, pady=7,
                               takefocus=False, cursor="hand2" if item["state"] == "normal" else "arrow",
                               command=lambda i=index: self.invoke(i))
            button.pack(fill="x")
            button.bind("<Enter>", lambda _e, i=index: self._activate(i))
            self.rows[index] = button
        win.update_idletasks()
        width, height = max(width, win.winfo_reqwidth()), win.winfo_reqheight()
        left, top, right, bottom = _work_area(self.root, x, y)
        x, y = max(left, min(x, right - width)), max(top, min(y, bottom - height))
        win.geometry("%dx%d%+d%+d" % (width, height, x, y))
        win.bind("<Escape>", lambda _e: self.destroy())
        win.bind("<Up>", lambda _e: self._step(-1))
        win.bind("<Down>", lambda _e: self._step(1))
        win.bind("<Return>", lambda _e: self.invoke(self.active) if self.active is not None else None)
        win.bind("<ButtonPress-1>", self._outside)
        win.bind("<ButtonPress-3>", self._outside)
        win.bind("<FocusOut>", self._focus_out)
        win.deiconify()
        win.update_idletasks()
        _place_and_round(win, x, y, width, height)
        win.grab_set()
        win.focus_force()
        return self

    def destroy(self, restore_focus=True):
        win, self.window = self.window, None
        self.rows = {}
        self.active = None
        if win is not None:
            try:
                if win.grab_current() is win:
                    win.grab_release()
                win.destroy()
                if restore_focus and self.previous_focus is not None and self.previous_focus.winfo_exists():
                    self.previous_focus.focus_set()
            except tk.TclError:
                pass
