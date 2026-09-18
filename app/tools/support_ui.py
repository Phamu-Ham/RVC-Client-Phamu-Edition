"""Explicit, local-only support export from the engine settings panel."""
import datetime as dt
from tkinter import filedialog

from tools.dialog_widgets import style_button
from tools.themed_dialog import create_dialog
from tools.yozakura_theme import YOZAKURA, YOZAKURA_FONT


def show_support(sg, parent, app_root, audio=None):
    from tools.support_log import export_bundle, record

    def text(value, **kwargs):
        return sg.Text(value, background_color=YOZAKURA["card"],
                       text_color=YOZAKURA["text"], **kwargs)
    dialog = create_dialog(sg, parent, "問い合わせ用ログ", [
        [text("エラーの記録と、動作環境の情報をZIPにまとめます。")],
        [text("音声・モデル・画像・設定ファイルは含みません。")],
        [text("パス等は伏せ字化します。送信前に内容を確認してください。")],
        [text("自動送信はしません。BOOTHのメッセージで状況をお知らせください。",
              font=(YOZAKURA_FONT, 9))],
        [text("", key="result", size=(62, 3), pad=(0, (12, 8)))],
        [sg.Button("ZIPを保存", key="save"), sg.Button("閉じる", key="close")],
    ])
    try:
        style_button(dialog["save"], primary=True, width=120)
        style_button(dialog["close"], width=90)
        while True:
            event, _ = dialog.read()
            if event in (sg.WINDOW_CLOSED, "close", "_dialog_close"):
                return
            if event != "save":
                continue
            path = filedialog.asksaveasfilename(
                parent=dialog.TKroot, title="問い合わせ用ログを保存",
                initialfile="Phamu-support-%s.zip" % dt.datetime.now().strftime("%Y%m%d-%H%M%S"),
                defaultextension=".zip", filetypes=[("ZIP", "*.zip")])
            if not path:
                continue
            try:
                export_bundle(app_root, path, audio)
                dialog["result"].update("保存しました。ZIPの内容を確認してから共有してください。")
                record("Support bundle exported by user (destination omitted)")
            except FileExistsError:
                dialog["result"].update("同名のファイルがあります。別の名前で保存してください。")
            except OSError as error:
                record("Support export failed: %s" % error)
                dialog["result"].update("保存できませんでした。空き容量・保存先の権限を確認してください。")
    finally:
        dialog.close()
