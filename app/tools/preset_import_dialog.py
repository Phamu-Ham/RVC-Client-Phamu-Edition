"""File import form. Selecting files does not unpickle or execute a model."""
import tkinter as tk
from tools.yozakura_theme import YOZAKURA, YOZAKURA_FONT
from tools.preset_import import classify_dropped_files
from tools.dialog_widgets import rounded_entry, style_button, DropSurface
from tools.themed_dialog import create_dialog


def attach_file_drop(dialog, entries, surface):
    """Attach native TkDND to this dialog only, without replacing Tk's WndProc."""
    from tkinterdnd2 import TkinterDnD, DND_FILES, COPY, REFUSE_DROP

    TkinterDnD.require(dialog.TKroot)

    def on_drop(event):
        surface.highlight(False)
        try:
            selected = classify_dropped_files(dialog.TKroot.tk.splitlist(event.data))
            # A new model must not silently inherit an Index for another voice.
            if ("model" in selected and "index" not in selected
                    and selected["model"] != dialog["model"].get()):
                selected["index"] = ""
            for key, path in selected.items():
                dialog[key].update(path)
                entries[key].xview_moveto(1)
            dialog["result"].update("振り分けました。「追加」で本体内にコピーします。",
                                     text_color=YOZAKURA["muted"])
            return COPY
        except (OSError, ValueError, tk.TclError) as error:
            dialog["result"].update(str(error), text_color=YOZAKURA["warning"])
            return REFUSE_DROP

    def on_enter(_event):
        surface.highlight(True)
        return COPY

    targets = [surface.canvas, *entries.values(),
               *(dialog[key + "_surface"].TKCanvas for key in entries)]
    registered = []
    try:
        for widget in targets:
            widget.drop_target_register(DND_FILES)
            registered.append(widget)
            widget.dnd_bind("<<DropEnter>>", on_enter)
            widget.dnd_bind("<<DropPosition>>", lambda _event: COPY)
            widget.dnd_bind("<<DropLeave>>", lambda _event: surface.highlight(False))
            widget.dnd_bind("<<Drop>>", on_drop)
    except Exception:
        for widget in registered:
            widget.drop_target_unregister()
        raise

    def cleanup():
        for widget in registered:
            try:
                widget.drop_target_unregister()
            except tk.TclError:
                pass
    return cleanup


def choose_preset_files(sg, parent):
    def text(label, **kwargs):
        return sg.Text(label, background_color=YOZAKURA["card"],
                       text_color=kwargs.pop("text_color", YOZAKURA["text"]), **kwargs)

    def file_row(key, file_type, pattern):
        return [sg.Canvas(size=(432, 44), key=key + "_surface",
                          background_color=YOZAKURA["card"], pad=((0, 14), (0, 8))),
                sg.Input(key=key, visible=False),
                sg.FileBrowse("選択", key=key + "_browse", target=key,
                              pad=(0, 0), file_types=((file_type, pattern),))]

    layout = [
        [sg.Canvas(size=(536, 92), key="drop_zone", background_color=YOZAKURA["card"],
                   pad=(0, (0, 16)))],
        [text("RVCモデル（.pth）", pad=(0, (0, 6)))],
        file_row("model", "RVCモデル", "*.pth"),
        [text("Indexファイル（.index）・省略可", pad=(0, (4, 6)))],
        file_row("index", "Index", "*.index"),
        [text("元ファイルはそのまま、本体内にコピーします。", pad=(0, (8, 2)),
              text_color=YOZAKURA["muted"])],
        [text("同名の別ファイルは連番で追加。Pitchなどは追加後に調整できます。",
              font=(YOZAKURA_FONT, 9), pad=(0, 2), text_color=YOZAKURA["muted"])],
        [text("ご自身で用意した、信頼できる配布元のモデルを選んでください。",
              font=(YOZAKURA_FONT, 9), pad=(0, 2), text_color=YOZAKURA["muted"])],
        [text("", key="result", size=(60, 2), pad=(0, (10, 4)), text_color=YOZAKURA["muted"])],
        [sg.Button("追加", key="submit", pad=((0, 10), (0, 0))),
         sg.Button("キャンセル", key="cancel", pad=(0, 0))],
    ]
    root = parent.TKroot
    root.update_idletasks()
    location = (max(0, root.winfo_rootx() + (root.winfo_width()-584)//2),
                max(0, root.winfo_rooty() + (root.winfo_height()-548)//2))
    dialog = create_dialog(sg, parent, "プリセット追加", layout, location=location)
    dialog["_dialog_title"].update("プリセットを追加")
    cleanup = lambda: None
    try:
        entries = {key: rounded_entry(dialog, key) for key in ("model", "index")}
        for key in ("model_browse", "index_browse", "submit", "cancel"):
            style_button(dialog[key], primary=(key == "submit"), width=104 if key == "cancel" else 90)
        surface = DropSurface(dialog["drop_zone"].TKCanvas)
        try:
            cleanup = attach_file_drop(dialog, entries, surface)
        except (ImportError, RuntimeError, OSError, tk.TclError) as error:
            surface.unavailable()
            print("Preset file drop unavailable: %s" % error)
        entries["model"].focus_set()
        while True:
            event, values = dialog.read()
            if event in (sg.WINDOW_CLOSED, "cancel", "_dialog_close"):
                return None
            if event == "submit":
                if not values["model"].strip():
                    dialog["result"].update("RVCモデル（.pth）を選んでください。",
                                             text_color=YOZAKURA["warning"])
                    continue
                return values["model"].strip(), values["index"].strip()
    finally:
        cleanup()
        dialog.close()
