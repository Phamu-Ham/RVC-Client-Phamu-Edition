"""Themed zoom/pan crop dialog; only confirmation creates a new image."""
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from tools.dialog_widgets import style_button
from tools.preset_image_crop import CropState, load_crop_source, save_crop
from tools.preset_artwork import render_preset_image_preview, render_preset_thumbnail
from tools.yozakura_theme import YOZAKURA, YOZAKURA_FONT


class CropCanvas:
    def __init__(self, dialog, source, model_name):
        self.dialog, self.model_name = dialog, model_name
        self.canvas = dialog["crop_canvas"].TKCanvas
        self.state = CropState(*source.size)
        self.proxy = source.copy()
        self.proxy.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        self.pending = None
        self.pointer = None
        self.closed = False
        self.canvas.configure(bd=0, highlightthickness=0, cursor="fleur")
        self.item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", lambda event: self.zoom_by(1.1))
        self.canvas.bind("<Button-5>", lambda event: self.zoom_by(1/1.1))
        self.canvas.bind("<Configure>", lambda event: self.schedule())
        self.canvas.bind("<Double-Button-1>", lambda event: self.reset())

    def frame(self):
        width, height = max(80, self.canvas.winfo_width()), max(80, self.canvas.winfo_height())
        fh = min(height-32, (width-40) / self.state.aspect)
        fw = fh * self.state.aspect
        return (width-fw)/2, (height-fh)/2, fw, fh

    def press(self, event):
        self.pointer = event.x, event.y

    def drag(self, event):
        if self.pointer is not None:
            _, _, fw, fh = self.frame()
            self.state.pan(event.x-self.pointer[0], event.y-self.pointer[1], (fw, fh))
            self.pointer = event.x, event.y
            self.schedule()

    def release(self, event):
        self.pointer = None

    def wheel(self, event):
        if event.delta:
            self.zoom_by(1.1 if event.delta > 0 else 1/1.1)
        return "break"

    def zoom_by(self, factor):
        self.state.set_zoom(self.state.zoom * factor)
        self.schedule()
        return "break"

    def reset(self):
        self.state.reset()
        self.schedule()

    def schedule(self):
        if not self.closed and self.pending is None:
            # Coalesce drag events so large source images don't stall the UI.
            self.pending = self.canvas.after(20, self.redraw)

    def redraw(self):
        self.pending = None
        if self.closed:
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        left, top, fw, fh = self.frame()
        x0, y0, x1, y1 = self.state.box()
        sx, sy = (x1-x0)/fw, (y1-y0)/fh
        extent = (x0-left*sx, y0-top*sy, x1+(width-left-fw)*sx, y1+(height-top-fh)*sy)
        px, py = self.proxy.width/self.state.width, self.proxy.height/self.state.height
        extent = tuple(v * (px if i % 2 == 0 else py) for i, v in enumerate(extent))
        view = self.proxy.transform((width, height), Image.Transform.EXTENT, extent,
                                    Image.Resampling.BILINEAR)
        background = Image.new("RGBA", view.size, YOZAKURA["card_alt"])
        background.alpha_composite(view)
        overlay = Image.new("RGBA", view.size)
        draw = ImageDraw.Draw(overlay)
        right, bottom = left+fw, top+fh
        for box in ((0, 0, width, top), (0, bottom, width, height),
                    (0, top, left, bottom), (right, top, width, bottom)):
            draw.rectangle(box, fill=(0, 0, 0, 135))
        draw.rectangle((left, top, right, bottom), outline=YOZAKURA["pink_light"], width=2)
        for part in (1/3, 2/3):
            draw.line((left+fw*part, top, left+fw*part, bottom), fill=(255, 255, 255, 75))
            draw.line((left, top+fh*part, right, top+fh*part), fill=(255, 255, 255, 75))
        background.alpha_composite(overlay)
        self.photo = ImageTk.PhotoImage(background, master=self.canvas)
        self.canvas.itemconfigure(self.item, image=self.photo)
        cropped = self.state.render(self.proxy, (round(400*self.state.aspect), 400))
        self.dialog["portrait_preview"].update(data=render_preset_image_preview(
            model_name=self.model_name, size=(108, 144), source_image=cropped))
        self.dialog["icon_preview"].update(data=render_preset_thumbnail(
            model_name=self.model_name, size=(104, 122), source_image=cropped))
        self.dialog["zoom_percent"].update("%d%%" % round(self.state.zoom*100))

    def close(self):
        self.closed = True
        if self.pending is not None:
            self.canvas.after_cancel(self.pending)
            self.pending = None
        self.proxy.close()


def edit_preset_image(sg, parent, source_path, app_root, model_name=""):
    source = load_crop_source(source_path)
    dialog = controller = None

    def text(label, **kwargs):
        return sg.Text(label, background_color=YOZAKURA["card"],
                       text_color=kwargs.pop("text_color", YOZAKURA["text"]), **kwargs)

    try:
        layout = [
            [text("画像の範囲を調整", font=(YOZAKURA_FONT, 15, "bold"), pad=(0, (0, 8)))],
            [text("ドラッグで移動 ／ ホイール・＋−で拡大縮小", font=(YOZAKURA_FONT, 9),
                  text_color=YOZAKURA["muted"], pad=(0, (0, 12)))],
            [sg.Canvas(size=(360, 360), key="crop_canvas", background_color=YOZAKURA["card_alt"],
                       pad=((0, 20), (0, 10))),
             sg.Column([
                 [text("モデル画像", font=(YOZAKURA_FONT, 9), pad=(0, (0, 6)))],
                 [sg.Image(key="portrait_preview", size=(108, 144), pad=(0, (0, 14)),
                           background_color=YOZAKURA["card"])],
                 [text("一覧アイコン", font=(YOZAKURA_FONT, 9), pad=(0, (0, 6)))],
                 [sg.Image(key="icon_preview", size=(104, 122), pad=(0, 0),
                           background_color=YOZAKURA["card"])],
             ], background_color=YOZAKURA["card"], pad=(0, 0), vertical_alignment="top",
                element_justification="center")],
            [sg.Radio("縦長", "crop_aspect", key="portrait", default=True, enable_events=True,
                      background_color=YOZAKURA["card"], text_color=YOZAKURA["text"], pad=((0, 8), 0)),
             sg.Radio("正方形", "crop_aspect", key="square", enable_events=True,
                      background_color=YOZAKURA["card"], text_color=YOZAKURA["text"], pad=((0, 20), 0)),
             sg.Button("−", key="zoom_out", pad=((0, 6), 0)),
             text("100%", key="zoom_percent", size=(5, 1), justification="center", pad=(0, 0)),
             sg.Button("＋", key="zoom_in", pad=((6, 14), 0)),
             sg.Button("リセット", key="reset", pad=(0, 0))],
            [text("元画像は変更しません。アニメーション画像は先頭フレームを使います。",
                  key="result", size=(58, 2), font=(YOZAKURA_FONT, 9),
                  text_color=YOZAKURA["muted"], pad=(0, (12, 8)))],
            [sg.Push(background_color=YOZAKURA["card"]),
             sg.Button("この範囲を使う", key="submit", pad=((0, 10), 0)),
             sg.Button("キャンセル", key="cancel", pad=(0, 0))],
        ]
        dialog = sg.Window("画像の範囲を調整", layout, modal=True, finalize=True,
                           keep_on_top=True, background_color=YOZAKURA["card"],
                           margins=(22, 18), font=(YOZAKURA_FONT, 10))
        for key, width in (("zoom_out", 38), ("zoom_in", 38), ("reset", 88),
                           ("submit", 150), ("cancel", 104)):
            style_button(dialog[key], primary=(key == "submit"), width=width)
        root = parent.TKroot
        dialog.refresh()
        get_area = getattr(root, "_rvc_get_work_area", None)
        ax, ay, aw, ah = get_area() if get_area else (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
        dw, dh = dialog.TKroot.winfo_width(), dialog.TKroot.winfo_height()
        x = min(max(ax+8, root.winfo_rootx()+(root.winfo_width()-dw)//2), ax+max(8, aw-dw-8))
        y = min(max(ay+8, root.winfo_rooty()+(root.winfo_height()-dh)//2), ay+max(8, ah-dh-40))
        dialog.move(x, y)
        controller = CropCanvas(dialog, source, model_name or "プレビュー")
        dialog._preset_crop_controller = controller
        controller.redraw()
        while True:
            event, values = dialog.read()
            if event in (sg.WINDOW_CLOSED, "cancel"):
                return None
            if event == "zoom_in":
                controller.zoom_by(1.1)
            elif event == "zoom_out":
                controller.zoom_by(1/1.1)
            elif event == "reset":
                controller.reset()
            elif event in ("portrait", "square"):
                controller.state.set_aspect(1.0 if event == "square" else 0.75)
                controller.schedule()
            elif event == "submit":
                try:
                    return save_crop(source, controller.state, app_root)
                except (OSError, ValueError) as error:
                    dialog["result"].update("保存できませんでした: " + str(error), text_color=YOZAKURA["warning"])
    finally:
        if controller is not None:
            controller.close()
        if dialog is not None:
            dialog.close()
        source.close()
