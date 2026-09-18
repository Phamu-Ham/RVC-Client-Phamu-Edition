"""Tk-thread-only visual feedback; never controls the audio engine."""
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk, ImageFilter
from tools.yozakura_theme import YOZAKURA


class TransportIndicator:
    STYLES = {
        "stopped": (None, "変換のON／OFF　■ 停止中"),
        "vc": (YOZAKURA["pink_light"], "変換のON／OFF　● 変換中"),
        "im": (YOZAKURA["warning"], "変換のON／OFF　● 入力音を確認中"),
    }

    def __init__(self, window):
        self.window = window
        self.frame = window["card_transport"].Widget
        self.state = None
        self.original_corners = self.frame._yozakura_corner_images
        self.edges = tuple(tk.Label(self.frame, bd=0, highlightthickness=0)
                           for _ in range(4))
        self.artwork = ()
        self.render_key = None
        self.resize_timer = None
        self.frame.bind("<Configure>", self._on_resize, add="+")
        self.set_state("stopped")

    def _on_resize(self, event):
        if event.widget is not self.frame:
            return
        if self.resize_timer is not None:
            self.frame.after_cancel(self.resize_timer)
        self.resize_timer = self.frame.after(50, self._paint_border)

    def refresh_theme(self):
        self.STYLES = {
            "stopped": (None, "変換のON／OFF　■ 停止中"),
            "vc": (YOZAKURA["pink_light"], "変換のON／OFF　● 変換中"),
            "im": (YOZAKURA["warning"], "変換のON／OFF　● 入力音を確認中"),
        }
        self.original_corners = self.frame._yozakura_corner_images
        state, self.state = self.state or "stopped", None
        self.set_state(state)

    def _paint_border(self):
        self.resize_timer = None
        try:
            color = self.STYLES[self.state][0]
            if color is None or not self.frame.winfo_exists():
                return
            width, height = self.frame.winfo_width(), self.frame.winfo_height()
            key = (self.state, width, height)
            if key == self.render_key or min(width, height) < 32:
                return
            scale, radius, edge = 3, 15, 8
            size = (width * scale, height * scale)
            base = Image.new("RGBA", size, YOZAKURA["bg"])
            ImageDraw.Draw(base).rounded_rectangle(
                (0, 0, size[0]-1, size[1]-1), radius=radius*scale, fill=YOZAKURA["card"])
            line = Image.new("RGBA", size)
            box = (3*scale, 3*scale, size[0]-3*scale-1, size[1]-3*scale-1)
            ImageDraw.Draw(line).rounded_rectangle(
                box, radius=(radius-3)*scale, outline=color, width=2*scale)
            glow = line.filter(ImageFilter.GaussianBlur(2*scale))
            base = Image.alpha_composite(Image.alpha_composite(base, glow), line)
            base = base.resize((width, height), Image.Resampling.LANCZOS)
            boxes = (
                (0, 0, radius, radius), (width-radius, 0, width, radius),
                (0, height-radius, radius, height), (width-radius, height-radius, width, height),
                (radius, 0, width-radius, edge), (radius, height-edge, width-radius, height),
                (0, radius, edge, height-radius), (width-edge, radius, width, height-radius),
            )
            # Keep only eight narrow strips, never a full-size overlay over controls.
            images = tuple(ImageTk.PhotoImage(base.crop(box), master=self.frame) for box in boxes)
            for label, image, box in zip(
                    self.frame._yozakura_corner_labels + self.edges, images, boxes):
                x, y, right, bottom = box
                label.configure(image=image)
                label.place(x=x, y=y, width=right-x, height=bottom-y)
                label.lift()
            self.artwork = images
            self.render_key = key
        except tk.TclError:
            return

    def set_state(self, state):
        if state == self.state:
            return
        try:
            if not self.frame.winfo_exists():
                return
            if self.resize_timer is not None:
                self.frame.after_cancel(self.resize_timer)
                self.resize_timer = None
            color, title = self.STYLES[state]
            self.window["card_transport_title"].update(title)
            self.state = state
            self.render_key = None
            if color is None:
                for edge in self.edges:
                    edge.place_forget()
                for label, image in zip(self.frame._yozakura_corner_labels, self.original_corners):
                    label.configure(image=image)
                self.artwork = ()
            else:
                self._paint_border()
        except tk.TclError:
            # Window-close cleanup can run after the native widgets are destroyed.
            return
