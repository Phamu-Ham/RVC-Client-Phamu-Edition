"""Gallery context actions and a themed 30-day preset recycle bin."""
from pathlib import Path
import threading
import tkinter as tk

from configs import preset_library as library
from configs.model_presets import model_name_from_path, load_model_preset, model_identity
from tools.dialog_widgets import rounded_entry, style_button
from tools.yozakura_theme import YOZAKURA, YOZAKURA_FONT, PRESET_GALLERY_PAGE_SIZE

ACTION_EVENT = "preset_management"
MAINTENANCE_EVENT = "preset_trash_maintenance"
MAINTENANCE_DONE = "preset_trash_maintenance_done"


def _text(sg, text, **kwargs):
    return sg.Text(text, background_color=YOZAKURA["card"], text_color=YOZAKURA["text"], **kwargs)


def _dialog(sg, parent, title, layout):
    root = parent.TKroot
    header = sg.Column([[
        _text(sg, title, key="_dialog_title", font=(YOZAKURA_FONT, 14, "bold"), expand_x=True, pad=(0, 0)),
        sg.Canvas(size=(38, 38), key="_dialog_close", pad=(0, 0),
                  background_color=YOZAKURA["card"], tooltip="閉じる（Esc）")]],
        key="_dialog_header", expand_x=True, background_color=YOZAKURA["card"], pad=(0, (0, 16)))
    dialog = sg.Window(title, [[header]] + layout, modal=True, finalize=True, keep_on_top=True,
                     no_titlebar=True,
                     background_color=YOZAKURA["card"], margins=(24, 20),
                     font=(YOZAKURA_FONT, 10),
                     location=(max(0, root.winfo_rootx() + 60), max(0, root.winfo_rooty() + 80)))
    close = dialog["_dialog_close"].TKCanvas
    close.configure(bd=0, highlightthickness=0, cursor="hand2", takefocus=True)
    close.create_oval(3, 3, 35, 35, fill=YOZAKURA["card_alt"], outline="", tags="surface")
    close.create_line(15, 15, 23, 23, fill=YOZAKURA["text"], width=1.5, capstyle="round", tags="cross")
    close.create_line(23, 15, 15, 23, fill=YOZAKURA["text"], width=1.5, capstyle="round", tags="cross")
    close.bind("<Enter>", lambda _e: close.itemconfigure("cross", fill=YOZAKURA["pink_light"]))
    close.bind("<Leave>", lambda _e: close.itemconfigure("cross", fill=YOZAKURA["text"]))
    for sequence in ("<Button-1>", "<Return>", "<space>"):
        close.bind(sequence, lambda _e: dialog.write_event_value("_dialog_close", None))
    dialog.TKroot.focus_set()
    from tools.themed_dialog import style_dialog
    style_dialog(dialog, "_dialog_close")
    return dialog


def confirm_delete(sg, parent, name):
    dialog = _dialog(sg, parent, "プリセットを削除", [
        [_text(sg, "このプリセットをゴミ箱へ移しますか？", font=(YOZAKURA_FONT, 12, "bold"))],
        [_text(sg, name, size=(45, 2))],
        [_text(sg, "削除から30日間は、アプリ内のゴミ箱から復元できます。")],
        [_text(sg, "PTH・Index・画像本体は移動・削除しません。")],
        [_text(sg, "30日経過後、設定だけをWindowsのゴミ箱へ移します。")],
        [sg.Button("ゴミ箱へ移す", key="delete"), sg.Button("キャンセル", key="cancel")],
    ])
    try:
        style_button(dialog["delete"], primary=True, width=130)
        style_button(dialog["cancel"], width=104)
        event, _ = dialog.read()
        return event == "delete"
    finally:
        dialog.close()


def ask_name(sg, parent, current, kind):
    suffix = ".pth" if kind == "model" else ".index"
    title = "モデル名を変更" if kind == "model" else "Index名を変更"
    dialog = _dialog(sg, parent, title, [
        [_text(sg, "ファイル名（" + suffix + "）")],
        [sg.Canvas(size=(432, 44), key="name_surface", background_color=YOZAKURA["card"]),
         sg.Input(Path(current).stem, key="name", visible=False)],
        [_text(sg, "拡張子は自動で付きます。保存設定の紐づけも引き継ぎます。")],
        [_text(sg, "同じファイルを参照する他のプリセットにも反映されます。")],
        [sg.Button("変更", key="submit"), sg.Button("キャンセル", key="cancel")],
    ])
    try:
        entry = rounded_entry(dialog, "name")
        style_button(dialog["submit"], primary=True)
        style_button(dialog["cancel"], width=104)
        entry.focus_set()
        entry.selection_range(0, "end")
        event, values = dialog.read()
        return values["name"] if event == "submit" else None
    finally:
        dialog.close()


def refresh_library(gui, root):
    gui.preset_gallery_catalog = gui.discover_model_presets()
    gui.show_preset_gallery_page(gui.preset_gallery_page)
    count = len(library.list_deleted(root))
    gui.window["preset_trash"].update("ゴミ箱（%d）" % count)


def _same(a, b, root):
    return bool(a and b and model_identity(a, root) == model_identity(b, root))


def _clear_current(gui, values):
    gui.current_model_path = ""
    gui.loaded_model_preset = False
    for key in ("pth_path", "index_path", "preset_image_path"):
        values[key] = ""
        gui.window[key].update("")
        if key in gui.path_displays:
            gui.path_displays[key].set("")
    gui.window["active_model_name"].update("モデル未選択")
    gui.refresh_preset_image("", "")
    gui.update_preset_status("プリセットをゴミ箱へ移しました")


def perform_action(gui, sg, root, action, pth_path, values):
    if gui.stream_is_active():
        sg.popup("変換を停止してからプリセットを整理してください。", keep_on_top=True)
        return
    if getattr(gui, "_preset_maintenance_running", False):
        sg.popup("ゴミ箱を整理中です。少し待ってから操作してください。", keep_on_top=True)
        return
    try:
        preset = load_model_preset(pth_path, root)
        if preset is None:
            raise ValueError("このプリセットは現在利用できません。一覧を確認してください。")
        if action == "delete":
            if not confirm_delete(sg, gui.window, model_name_from_path(pth_path)):
                return
            # Capture unsaved settings/artwork for the preset actually being deleted.
            if _same(gui.current_model_path, pth_path, root):
                gui.save_current_model_preset(values)
            library.delete_preset(root, pth_path)
            if _same(gui.current_model_path, pth_path, root):
                _clear_current(gui, values)
            gui.persist_session(values)
        else:
            key = "pth_path" if action == "model" else "index_path"
            path = pth_path if action == "model" else preset.get("index_path", "")
            if action == "index" and _same(gui.current_model_path, pth_path, root):
                path = values.get("index_path", path)
            if not path:
                raise ValueError("このプリセットにはIndexが設定されていません。")
            name = ask_name(sg, gui.window, path, action)
            if name is None:
                return
            if _same(gui.current_model_path, pth_path, root):
                gui.save_current_model_preset(values)
            old, new = library.rename_file(root, pth_path, action, name)
            if _same(values.get(key), old, root):
                values[key] = new
                gui.window[key].update(new)
                gui.path_displays[key].set(new)
            if action == "model" and _same(gui.current_model_path, old, root):
                gui.current_model_path = new
                gui.window["active_model_name"].update(model_name_from_path(new))
                gui.refresh_preset_image(values.get("preset_image_path", ""), model_name_from_path(new))
            gui.persist_session(values)
            gui.update_preset_status("ファイル名を変更しました")
        refresh_library(gui, root)
    except (OSError, ValueError) as error:
        sg.popup_error("プリセットを変更できませんでした", str(error), keep_on_top=True)


def show_trash(gui, sg, root):
    if gui.stream_is_active() or getattr(gui, "_preset_maintenance_running", False):
        sg.popup("変換・ゴミ箱の整理が終わってから開いてください。", keep_on_top=True)
        return
    rows = library.list_deleted(root)

    def labels():
        return ["%s　｜　削除 %s　｜　%s" % (r["model_name"], r["deleted_at"][:10],
                "残り%d日" % r["remaining_days"] if r["remaining_days"] else "Windowsゴミ箱への移動待ち") for r in rows]

    dialog = _dialog(sg, gui.window, "プリセットのゴミ箱", [
        [_text(sg, "削除から30日間は復元できます。元のPTH・Index・画像は残ります。")],
        [sg.Listbox(labels(), key="entries", size=(60, 10), enable_events=True,
                    background_color=YOZAKURA["card_alt"], text_color=YOZAKURA["text"],
                    select_mode=sg.LISTBOX_SELECT_MODE_SINGLE)],
        [_text(sg, "復元するプリセットを選んでください。" if rows else "ゴミ箱は空です。", key="status", size=(60, 2))],
        [_text(sg, "30日経過後はアプリ起動時などに設定をWindowsのゴミ箱へ移します。", font=(YOZAKURA_FONT, 9))],
        [sg.Button("復元", key="restore", disabled=not rows), sg.Button("閉じる", key="close")],
    ])
    try:
        style_button(dialog["restore"], primary=True)
        style_button(dialog["close"])
        dialog["entries"].Widget.configure(highlightthickness=0, relief="flat", bd=0)
        from tools.themed_dialog import ThemedListScrollbar, set_button_disabled
        ThemedListScrollbar(dialog["entries"].Widget)
        set_button_disabled(dialog["restore"], not rows)
        while True:
            event, _ = dialog.read()
            if event in (sg.WINDOW_CLOSED, "close", "_dialog_close"):
                return
            if event != "restore":
                continue
            selected = dialog["entries"].Widget.curselection()
            if not selected:
                dialog["status"].update("復元するプリセットを選んでください。")
                continue
            try:
                row = rows[int(selected[0])]
                library.restore_preset(root, row["id"])
                refresh_library(gui, root)
                rows = library.list_deleted(root)
                dialog["entries"].update(labels())
                set_button_disabled(dialog["restore"], not rows)
                dialog["status"].update("「%s」を復元しました。プリセット一覧から選べます。" % row["model_name"])
            except (OSError, ValueError) as error:
                dialog["status"].update(str(error))
    finally:
        dialog.close()


def build_context_menu(gui, root, slot):
    entry = gui.preset_gallery_entries.get("preset_gallery::%d" % slot)
    if not entry:
        return None
    from tools.preset_context_menu import PresetContextMenu
    menu = PresetContextMenu(gui.window.TKroot)
    disabled = gui.stream_is_active() or getattr(gui, "_preset_maintenance_running", False)
    for action, label in (("model", "モデル名を変更（.pth）"), ("index", "Index名を変更（.index）"),
                          ("delete", "プリセットを削除")):
        if action == "delete":
            menu.add_separator()
        menu.add_command(label=label, state="disabled" if disabled else "normal",
                         command=lambda a=action, p=entry["pth_path"]:
                         gui.window.write_event_value(ACTION_EVENT, (a, p)))
    return menu


def install_context_menu(gui, root):
    def popup(event, slot):
        previous = getattr(gui, "_preset_context_menu", None)
        if previous is not None:
            previous.destroy()
        menu = build_context_menu(gui, root, slot)
        if menu is None:
            return
        gui._preset_context_menu = menu
        menu.tk_popup(event.x_root, event.y_root)
        return "break"
    for slot in range(PRESET_GALLERY_PAGE_SIZE):
        gui.window["preset_gallery::%d" % slot].Widget.bind(
            "<Button-3>", lambda event, s=slot: popup(event, s))
    gui.window.TKroot.after(500, lambda: gui.window.write_event_value(MAINTENANCE_EVENT, None))


def maintenance(gui, root):
    if getattr(gui, "_preset_maintenance_running", False):
        return
    gui._preset_maintenance_running = True

    def worker():
        try:
            result = library.expire_deleted(root)
        except (OSError, ValueError) as error:
            result = ([], [str(error)])
        try:
            gui.window.write_event_value(MAINTENANCE_DONE, result)
        except (RuntimeError, tk.TclError):
            pass
    threading.Thread(target=worker, name="preset-trash-maintenance", daemon=True).start()


def maintenance_done(gui, root, result):
    gui._preset_maintenance_running = False
    moved, errors = result
    refresh_library(gui, root)
    if errors:
        gui.report_audio_status("ゴミ箱の整理を保留しました: " + errors[0])
    elif moved:
        gui.update_preset_status("期限を過ぎた設定%d件をWindowsのゴミ箱へ移しました" % len(moved))
    gui.window.TKroot.after(3600000, lambda: gui.window.write_event_value(MAINTENANCE_EVENT, None))
