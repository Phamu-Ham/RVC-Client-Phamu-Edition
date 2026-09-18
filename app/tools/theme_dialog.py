"""Appearance selection dialog; changes are applied at the next app launch."""
from tools.yozakura_theme import (
    YOZAKURA, ACTIVE_THEME_ID, THEME_NAMES, load_theme_preference, save_theme_preference,
)


def show_theme_dialog(sg, parent):
    current = THEME_NAMES[ACTIVE_THEME_ID]
    saved = THEME_NAMES[load_theme_preference()]
    layout = [
        [sg.Text("デザインテーマ", font=("Noto Sans JP", 14, "bold"))],
        [sg.Text("表示中：" + current)],
        [sg.Combo(list(THEME_NAMES.values()), default_value=saved, readonly=True,
                  key="theme", size=(24, 1))],
        [sg.Text("保存したテーマは、次回起動から反映されます。\n音声変換やプリセットの設定は変わりません。")],
        [sg.Text("", key="result", size=(42, 2), text_color=YOZAKURA["pink_light"])],
        [sg.Button("保存", key="save"), sg.Button("閉じる", key="close")],
    ]
    root = parent.TKroot
    dialog = sg.Window("デザインテーマ", layout, modal=True, finalize=True,
                       location=(root.winfo_rootx()+100, root.winfo_rooty()+100),
                       background_color=YOZAKURA["bg"])
    try:
        while True:
            event, values = dialog.read()
            if event in (sg.WINDOW_CLOSED, "close"):
                break
            if event == "save":
                selected = next(key for key, name in THEME_NAMES.items() if name == values["theme"])
                try:
                    save_theme_preference(selected)
                except (OSError, ValueError) as error:
                    dialog["result"].update("保存できませんでした：%s" % error)
                    continue
                dialog["result"].update(
                    "保存しました。現在と同じテーマです。" if selected == ACTIVE_THEME_ID else
                    "保存しました。アプリを起動し直すと反映されます。")
    finally:
        dialog.close()
