"""Frameless Tk window movement, resizing and taskbar integration."""
import sys
from tools.yozakura_theme import YOZAKURA


RESIZE_EDGE = 2
RESIZE_CORNER = 12


def resize_direction(x, y, width, height):
    """Only corner squares get a larger target; ordinary edges remain narrow."""
    if not (0 <= x < width and 0 <= y < height):
        return None
    left, right = x < RESIZE_CORNER, x >= width - RESIZE_CORNER
    top, bottom = y < RESIZE_CORNER, y >= height - RESIZE_CORNER
    if top and left:
        return "top_left"
    if top and right:
        return "top_right"
    if bottom and left:
        return "bottom_left"
    if bottom and right:
        return "bottom_right"
    if x < RESIZE_EDGE:
        return "left"
    if x >= width - RESIZE_EDGE:
        return "right"
    if y < RESIZE_EDGE:
        return "top"
    if y >= height - RESIZE_EDGE:
        return "bottom"
    return None


def enable_windows_taskbar(window):
    """Stable frameless Windows integration without a Python WndProc."""
    if sys.platform != "win32":
        return

    try:
        import ctypes
        import tkinter as tk
        from ctypes import wintypes

        root = window.TKroot
        root.update_idletasks()
        child_hwnd = root.winfo_id()
        # ctypes.windll caches function objects globally. Dialogs use their own
        # MONITORINFO types, so sharing its argtypes can crash later maximization.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        hwnd = user32.GetParent(child_hwnd) or child_hwnd

        gwl_style = -16
        gwl_exstyle = -20
        gwl_hwndparent = -8
        ws_caption = 0x00C00000
        ws_thickframe = 0x00040000
        ws_border = 0x00800000
        ws_dlgframe = 0x00400000
        ws_minimizebox = 0x00020000
        ws_maximizebox = 0x00010000
        ws_sysmenu = 0x00080000
        ws_ex_toolwindow = 0x00000080
        ws_ex_appwindow = 0x00040000
        ws_ex_windowedge = 0x00000100
        ws_ex_clientedge = 0x00000200
        swp_nomove = 0x0002
        swp_nosize = 0x0001
        swp_nozorder = 0x0004
        swp_framechanged = 0x0020
        swp_noactivate = 0x0010

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_ssize_t,
        ]

        # Hide across the style transition so Explorer registers one clean
        # app window. Remove every native frame bit; resizing is handled by
        # lightweight Tk overlays below, avoiding unsafe Python WndProc
        # callbacks during Windows modal resize loops.
        user32.ShowWindow(hwnd, 0)
        style = user32.GetWindowLongPtrW(hwnd, gwl_style)
        style &= ~(
            ws_caption | ws_thickframe | ws_border | ws_dlgframe
        )
        style |= ws_minimizebox | ws_maximizebox | ws_sysmenu
        user32.SetWindowLongPtrW(hwnd, gwl_style, style)

        exstyle = user32.GetWindowLongPtrW(hwnd, gwl_exstyle)
        exstyle &= ~(
            ws_ex_toolwindow | ws_ex_windowedge | ws_ex_clientedge
        )
        exstyle |= ws_ex_appwindow
        user32.SetWindowLongPtrW(hwnd, gwl_exstyle, exstyle)
        user32.SetWindowLongPtrW(hwnd, gwl_hwndparent, 0)
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            swp_nomove | swp_nosize | swp_nozorder | swp_framechanged,
        )

        root._rvc_window_hwnd = hwnd
        root._rvc_manual_maximized = False
        root._rvc_restore_geometry = None

        try:
            corner_preference = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                33,
                ctypes.byref(corner_preference),
                ctypes.sizeof(corner_preference),
            )
        except Exception:
            pass

        def get_work_area(point=None):
            monitor = (user32.MonitorFromPoint(wintypes.POINT(*point), 2)
                       if point is not None else user32.MonitorFromWindow(hwnd, 2))
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if monitor and user32.GetMonitorInfoW(
                monitor, ctypes.byref(info)
            ):
                return (
                    info.rcWork.left,
                    info.rcWork.top,
                    info.rcWork.right - info.rcWork.left,
                    info.rcWork.bottom - info.rcWork.top,
                )
            return (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())

        root._rvc_get_work_area = get_work_area

        def set_bounds(x, y, width, height):
            # Native screen coordinates also handle monitors left of / above
            # the primary; Tk's negative geometry offsets anchor to screen edges.
            if not user32.SetWindowPos(hwnd, None, int(x), int(y), int(width), int(height),
                                       swp_nozorder | swp_noactivate):
                raise ctypes.WinError(ctypes.get_last_error())

        def remember_bounds():
            return (root.winfo_width(), root.winfo_height(),
                    root.winfo_rootx(), root.winfo_rooty())

        def set_maximized(maximized, work_area=None, restore_bounds=None):
            if maximized == root._rvc_manual_maximized:
                return
            root.update_idletasks()
            if maximized:
                restore = restore_bounds or remember_bounds()
                x, y, width, height = work_area or get_work_area()
                set_bounds(x, y, width, height)
                root._rvc_restore_geometry = restore
            else:
                if root._rvc_restore_geometry is None:
                    return
                width, height, x, y = root._rvc_restore_geometry
                set_bounds(x, y, width, height)
            root._rvc_manual_maximized = maximized
            window["window_maximize"].update("❐" if maximized else "□")
            refresh_resize_cursors()

        root._rvc_toggle_maximize = lambda: set_maximized(not root._rvc_manual_maximized)

        window_control_widgets = {
            window[key].Widget
            for key in (
                "window_minimize",
                "window_maximize",
                "window_close",
                "theme_settings",
            )
            if key in window.AllKeysDict
        }

        move_state = {"active": False}

        def begin_window_move(event):
            local_y = event.y_root - root.winfo_rooty()
            local_x = event.x_root - root.winfo_rootx()
            if event.widget in window_control_widgets:
                return None
            if resize_direction(local_x, local_y, root.winfo_width(), root.winfo_height()):
                return None
            if local_x >= root.winfo_width() - 26:
                if local_x < root.winfo_width() - 7:
                    return None
            if (
                local_x < 7
                or local_x >= root.winfo_width() - 7
                or local_y < 7
                or local_y >= root.winfo_height() - 7
            ):
                return None
            if not 0 <= local_y < 64:
                return None
            move_state.update(
                active=True,
                moved=False,
                pointer_x=event.x_root,
                pointer_y=event.y_root,
                x=root.winfo_rootx(),
                y=root.winfo_rooty(),
                restore_bounds=(root._rvc_restore_geometry if root._rvc_manual_maximized
                                else remember_bounds()),
                anchor=min(1.0, max(0.0, local_x / max(1, root.winfo_width()))),
                header_y=local_y,
            )
            return "break"

        def drag_window(event):
            if not move_state.get("active"):
                return None
            if not move_state["moved"]:
                if max(abs(event.x_root - move_state["pointer_x"]),
                       abs(event.y_root - move_state["pointer_y"])) < 4:
                    return "break"
                move_state["moved"] = True
                if root._rvc_manual_maximized:
                    width, height, _, _ = root._rvc_restore_geometry
                    x = round(event.x_root - width * move_state["anchor"])
                    y = event.y_root - move_state["header_y"]
                    set_bounds(x, y, width, height)
                    root._rvc_manual_maximized = False
                    window["window_maximize"].update("□")
                    refresh_resize_cursors()
                    move_state.update(x=x, y=y, pointer_x=event.x_root,
                                      pointer_y=event.y_root)
            x = move_state["x"] + event.x_root - move_state["pointer_x"]
            y = move_state["y"] + event.y_root - move_state["pointer_y"]
            # No native move loop / Python WndProc, so audio and Tk keep running.
            set_bounds(x, y, root.winfo_width(), root.winfo_height())
            return "break"

        def finish_window_move(event):
            snap = move_state.get("active") and move_state.get("moved")
            move_state["active"] = False
            if snap:
                area = get_work_area((event.x_root, event.y_root))
                left, top, width, _ = area
                if left <= event.x_root < left + width and abs(event.y_root - top) <= 8:
                    set_maximized(True, area, move_state["restore_bounds"])
            return None

        root.bind("<ButtonPress-1>", begin_window_move, add="+")
        root.bind("<B1-Motion>", drag_window, add="+")
        root.bind("<ButtonRelease-1>", finish_window_move, add="+")

        resize_state = {"active": False}
        min_width = 800
        min_height = 600

        def start_resize(event, direction):
            if root._rvc_manual_maximized:
                return "break"
            resize_state.update(
                active=True,
                direction=direction,
                pointer_x=event.x_root,
                pointer_y=event.y_root,
                x=root.winfo_x(),
                y=root.winfo_y(),
                width=root.winfo_width(),
                height=root.winfo_height(),
            )
            return "break"

        def drag_resize(event):
            if not resize_state.get("active"):
                return "break"
            direction = resize_state["direction"]
            dx = event.x_root - resize_state["pointer_x"]
            dy = event.y_root - resize_state["pointer_y"]
            x = resize_state["x"]
            y = resize_state["y"]
            width = resize_state["width"]
            height = resize_state["height"]

            if "right" in direction:
                width = max(min_width, width + dx)
            if "bottom" in direction:
                height = max(min_height, height + dy)
            if "left" in direction:
                new_width = max(min_width, width - dx)
                x += width - new_width
                width = new_width
            if "top" in direction:
                new_height = max(min_height, height - dy)
                y += height - new_height
                height = new_height
            set_bounds(x, y, width, height)
            return "break"

        def finish_resize(_event):
            resize_state["active"] = False
            return "break"

        def begin_resize_from_edge(event):
            x = event.x_root - root.winfo_rootx()
            y = event.y_root - root.winfo_rooty()
            width = root.winfo_width()
            height = root.winfo_height()
            direction = resize_direction(x, y, width, height)
            if direction is None:
                return None
            return start_resize(event, direction)

        root.bind("<ButtonPress-1>", begin_resize_from_edge, add="+")
        root.bind("<B1-Motion>", drag_resize, add="+")
        root.bind("<ButtonRelease-1>", finish_resize, add="+")

        edge = RESIZE_EDGE
        corner = RESIZE_CORNER
        handle_specs = (
            ("top", "sb_v_double_arrow", dict(x=corner, y=0, relwidth=1, width=-(corner * 2), height=edge)),
            ("bottom", "sb_v_double_arrow", dict(x=corner, rely=1, y=-edge, relwidth=1, width=-(corner * 2), height=edge)),
            ("left", "sb_h_double_arrow", dict(x=0, y=corner, width=edge, relheight=1, height=-(corner * 2))),
            ("right", "sb_h_double_arrow", dict(relx=1, x=-edge, y=corner, width=edge, relheight=1, height=-(corner * 2))),
            ("top_left", "size_nw_se", dict(x=0, y=0, width=corner, height=corner)),
            ("top_right", "size_ne_sw", dict(relx=1, x=-corner, y=0, width=corner, height=corner)),
            ("bottom_left", "size_ne_sw", dict(x=0, rely=1, y=-corner, width=corner, height=corner)),
            ("bottom_right", "size_nw_se", dict(relx=1, rely=1, x=-corner, y=-corner, width=corner, height=corner)),
        )
        resize_handles = []
        for direction, cursor_name, placement in handle_specs:
            handle = tk.Frame(
                root,
                bg=YOZAKURA["bg"],
                bd=0,
                highlightthickness=0,
                cursor=cursor_name,
            )
            handle.place(**placement, bordermode="ignore")
            handle.bind(
                "<ButtonPress-1>",
                lambda event, value=direction: start_resize(event, value),
            )
            handle.bind("<B1-Motion>", drag_resize)
            handle.bind("<ButtonRelease-1>", finish_resize)
            resize_handles.append(handle)

        def refresh_resize_cursors():
            for handle, (_, cursor_name, _) in zip(resize_handles, handle_specs):
                handle.configure(cursor="arrow" if root._rvc_manual_maximized else cursor_name)

        def raise_handles(_event=None):
            for handle in resize_handles:
                handle.lift()

        root._rvc_resize_handles = resize_handles
        root.bind(
            "<Configure>",
            lambda event: root.after_idle(raise_handles)
            if event.widget is root else None,
            add="+",
        )
        root.after_idle(raise_handles)

        def show_as_app_window():
            user32.ShowWindow(hwnd, 5)
            root.deiconify()
            root.lift()
            root.focus_force()

        root.after(70, show_as_app_window)
    except Exception as error:
        try:
            window.TKroot.deiconify()
        except Exception:
            pass
        print("Windows taskbar registration failed: %s" % error)
