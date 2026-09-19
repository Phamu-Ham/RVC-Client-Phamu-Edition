import os
import sys
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.append(APP_ROOT)
if __name__ == "__main__":
    from tools.support_log import install as install_support_log
    install_support_log(APP_ROOT)
    print("起動中… 実行環境を読み込んでいます。画面が開くまでお待ちください。", flush=True)
from dotenv import load_dotenv
import shutil

os.chdir(APP_ROOT)
load_dotenv(os.path.join(APP_ROOT, ".env"))

os.environ["OMP_NUM_THREADS"] = "4"
if sys.platform == "darwin":
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

now_dir = os.getcwd()
import multiprocessing

flag_vc = False


def printt(strr, *args):
    if len(args) == 0:
        print(strr)
    else:
        print(strr % args)


def phase_vocoder(a, b, fade_out, fade_in):
    window = torch.sqrt(fade_out * fade_in)
    fa = torch.fft.rfft(a * window)
    fb = torch.fft.rfft(b * window)
    absab = torch.abs(fa) + torch.abs(fb)
    n = a.shape[0]
    if n % 2 == 0:
        absab[1:-1] *= 2
    else:
        absab[1:] *= 2
    phia = torch.angle(fa)
    phib = torch.angle(fb)
    deltaphase = phib - phia
    deltaphase = deltaphase - 2 * np.pi * torch.floor(deltaphase / 2 / np.pi + 0.5)
    w = 2 * np.pi * torch.arange(n // 2 + 1).to(a) + deltaphase
    t = torch.arange(n).unsqueeze(-1).to(a) / n
    result = (
        a * (fade_out**2)
        + b * (fade_in**2)
        + torch.sum(absab * torch.cos(w * t + phia), -1) * window / n
    )
    return result


if __name__ == "__main__":
    from io import BytesIO
    import json
    import multiprocessing
    import re
    import threading
    import time
    import traceback
    import tkinter as tk
    from multiprocessing import cpu_count
    from queue import Empty

    import librosa
    from tools.torchgate import TorchGate
    import numpy as np
    import PySimpleGUI as sg
    import sounddevice as sd
    import torch
    import torch.nn.functional as F
    import torchaudio.transforms as tat
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    print("起動中… 音声デバイスと画面を準備しています。", flush=True)

    from infer.lib.harvest_pool import HarvestPool
    from tools.runtime_support import DEBUG_REALTIME, debugt
    from i18n.i18n import I18nAuto
    from configs.config import Config
    from configs.model_presets import (
        find_index_for_model,
        load_model_preset,
        model_name_from_path,
        save_model_preset,
    )
    from configs.voicemeeter_presets import apply_voicemeeter_preset

    i18n = I18nAuto()

    from tools.yozakura_theme import (
        YOZAKURA, YOZAKURA_FONT, PRESET_IMAGE_SIZE,
        PRESET_THUMBNAIL_SIZE, PRESET_GALLERY_PAGE_SIZE,
    )
    from tools.window_chrome import enable_windows_taskbar
    from tools.app_identity import app_icon_path, configure_windows_app_id
    from tools.yozakura_theme import theme_button_label
    from tools.preset_artwork import (
        preset_image_preview_data, preset_thumbnail_data, preset_add_thumbnail_data,
    )

    configure_windows_app_id()

    def apply_yozakura_theme():
        """Register the night-cherry theme before constructing GUI elements."""
        sg.theme_add_new(
            "Yozakura",
            {
                "BACKGROUND": YOZAKURA["bg"],
                "TEXT": YOZAKURA["text"],
                "INPUT": YOZAKURA["card_alt"],
                "TEXT_INPUT": YOZAKURA["text"],
                "SCROLL": YOZAKURA["purple"],
                "BUTTON": (YOZAKURA["bg"], YOZAKURA["pink"]),
                "PROGRESS": (YOZAKURA["pink"], YOZAKURA["border"]),
                "BORDER": 0,
                "SLIDER_DEPTH": 0,
                "PROGRESS_DEPTH": 0,
            },
        )
        sg.theme("Yozakura")
        sg.set_options(
            icon=app_icon_path(),
            font=(YOZAKURA_FONT, 10),
            button_color=(YOZAKURA["bg"], YOZAKURA["pink"]),
            element_padding=(7, 5),
            margins=(18, 14),
            border_width=0,
            slider_border_width=0,
            slider_relief=sg.RELIEF_FLAT,
            use_custom_titlebar=False,
            titlebar_background_color=YOZAKURA["card"],
            titlebar_text_color=YOZAKURA["text"],
            titlebar_font=(YOZAKURA_FONT, 10, "bold"),
        )


    class YozakuraSlider:
        """Canvas-based slider with a rounded track and a separate value pill."""

        def __init__(
            self,
            window,
            canvas_key,
            value_key,
            minimum,
            maximum,
            resolution,
            value,
        ):
            self.window = window
            self.value_key = value_key
            self.minimum = float(minimum)
            self.maximum = float(maximum)
            self.resolution = float(resolution)
            self.canvas = window[canvas_key].TKCanvas
            self.width = 320
            self.height = 44
            self.track_left = 12
            self.track_right = 232
            self.track_y = 22
            self.value = self.minimum
            self.canvas.configure(
                width=self.width,
                height=self.height,
                bg=YOZAKURA["card"],
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
            self.canvas.bind("<Button-1>", self._on_pointer)
            self.canvas.bind("<B1-Motion>", self._on_pointer)
            self.set(value, notify=False)

        def _snap(self, value):
            steps = round((float(value) - self.minimum) / self.resolution)
            snapped = self.minimum + steps * self.resolution
            return min(self.maximum, max(self.minimum, snapped))

        def _format_value(self):
            if self.resolution >= 1:
                return str(int(round(self.value)))
            if self.resolution >= 0.1:
                return f"{self.value:.1f}"
            return f"{self.value:.2f}"

        def _rounded_rectangle(self, x1, y1, x2, y2, radius, **kwargs):
            points = [
                x1 + radius,
                y1,
                x2 - radius,
                y1,
                x2,
                y1,
                x2,
                y1 + radius,
                x2,
                y2 - radius,
                x2,
                y2,
                x2 - radius,
                y2,
                x1 + radius,
                y2,
                x1,
                y2,
                x1,
                y2 - radius,
                x1,
                y1 + radius,
                x1,
                y1,
            ]
            return self.canvas.create_polygon(points, smooth=True, **kwargs)

        def _draw(self):
            self.canvas.delete("all")
            ratio = (self.value - self.minimum) / (self.maximum - self.minimum)
            knob_x = self.track_left + ratio * (self.track_right - self.track_left)
            self.canvas.create_line(
                self.track_left,
                self.track_y,
                self.track_right,
                self.track_y,
                fill=YOZAKURA["border"],
                width=7,
                capstyle="round",
            )
            if knob_x > self.track_left:
                self.canvas.create_line(
                    self.track_left,
                    self.track_y,
                    knob_x,
                    self.track_y,
                    fill=YOZAKURA["pink"],
                    width=7,
                    capstyle="round",
                )
            self.canvas.create_oval(
                knob_x - 8,
                self.track_y - 8,
                knob_x + 8,
                self.track_y + 8,
                fill=YOZAKURA["pink_light"],
                outline=YOZAKURA["card"],
                width=3,
            )
            self._rounded_rectangle(
                248,
                6,
                318,
                38,
                12,
                fill=YOZAKURA["card_alt"],
                outline=YOZAKURA["border"],
                width=1,
            )
            self.canvas.create_text(
                283,
                22,
                text=self._format_value(),
                fill=YOZAKURA["pink_light"],
                font=(YOZAKURA_FONT, 10, "bold"),
            )

        def _on_pointer(self, event):
            x = min(self.track_right, max(self.track_left, event.x))
            ratio = (x - self.track_left) / (self.track_right - self.track_left)
            self.set(self.minimum + ratio * (self.maximum - self.minimum), notify=True)

        def set(self, value, notify=False):
            new_value = self._snap(value)
            changed = new_value != self.value
            if not changed and getattr(self, "_painted", False):
                return
            self.value = new_value
            self._draw()
            self._painted = True
            self.window[self.value_key].update(value=self.value)
            if notify and changed:
                self.window.write_event_value(self.value_key, self.value)


    class PresetMetricTile:
        """Rounded summary tile used in the active model card."""

        def __init__(self, window, canvas_key, label, value):
            self.canvas = window[canvas_key].TKCanvas
            self.label = label
            self.value = str(value)
            self.width = 98
            self.height = 64
            self.canvas.configure(
                width=self.width,
                height=self.height,
                bg=YOZAKURA["card"],
                bd=0,
                highlightthickness=0,
            )
            self.draw()

        def rounded_rectangle(self, x1, y1, x2, y2, radius, **kwargs):
            points = [
                x1 + radius, y1,
                x2 - radius, y1,
                x2, y1,
                x2, y1 + radius,
                x2, y2 - radius,
                x2, y2,
                x2 - radius, y2,
                x1 + radius, y2,
                x1, y2,
                x1, y2 - radius,
                x1, y1 + radius,
                x1, y1,
            ]
            return self.canvas.create_polygon(points, smooth=True, **kwargs)

        def draw(self):
            self.canvas.delete("all")
            self.rounded_rectangle(
                1,
                1,
                self.width - 1,
                self.height - 1,
                11,
                fill=YOZAKURA["card_alt"],
                outline=YOZAKURA["border"],
                width=1,
            )
            self.canvas.create_text(
                10,
                17,
                text=self.label,
                anchor="w",
                fill=YOZAKURA["muted"],
                font=(YOZAKURA_FONT, 8, "bold"),
            )
            self.canvas.create_text(
                10,
                43,
                text=self.value,
                anchor="w",
                fill=YOZAKURA["pink_light"],
                font=(YOZAKURA_FONT, 13, "bold"),
            )

        def set(self, value):
            if str(value) == self.value:
                return
            self.value = str(value)
            self.draw()

        def resize(self, width):
            """Fit the five summary tiles into narrower model panels."""
            width = max(76, int(width))
            if width == self.width:
                return
            self.width = width
            self.canvas.configure(width=self.width)
            self.draw()


    class RoundedPathDisplay:
        """Read-only rounded path surface backed by a hidden PSG input."""

        def __init__(self, window, canvas_key, value=""):
            import tkinter.font as tkfont

            self.element = window[canvas_key]
            self.canvas = self.element.TKCanvas
            self.value = str(value or "")
            self.width = 620
            self.height = 38
            self.hover = False
            self.font = tkfont.Font(
                root=self.canvas,
                family=YOZAKURA_FONT,
                size=10,
            )
            self.canvas.configure(
                width=self.width,
                height=self.height,
                bg=YOZAKURA["card"],
                bd=0,
                highlightthickness=0,
            )
            self.canvas.bind("<Enter>", self._on_enter)
            self.canvas.bind("<Leave>", self._on_leave)
            self.draw()
            self._update_tooltip()

        def rounded_rectangle(self, x1, y1, x2, y2, radius, **kwargs):
            points = [
                x1 + radius, y1,
                x2 - radius, y1,
                x2, y1,
                x2, y1 + radius,
                x2, y2 - radius,
                x2, y2,
                x2 - radius, y2,
                x1 + radius, y2,
                x1, y2,
                x1, y2 - radius,
                x1, y1 + radius,
                x1, y1,
            ]
            return self.canvas.create_polygon(points, smooth=True, **kwargs)

        def display_text(self):
            text = self.value or "未選択"
            available = self.width - 24
            if self.font.measure(text) <= available:
                return text
            shortened = text
            while len(shortened) > 4 and self.font.measure("…" + shortened) > available:
                shortened = shortened[2:]
            return "…" + shortened

        def draw(self):
            self.canvas.delete("all")
            self.rounded_rectangle(
                1,
                1,
                self.width - 1,
                self.height - 1,
                11,
                fill=YOZAKURA["card_alt"],
                outline=(YOZAKURA["pink"] if self.hover else YOZAKURA["border"]),
                width=1,
            )
            self.canvas.create_text(
                12,
                self.height // 2,
                text=self.display_text(),
                anchor="w",
                fill=YOZAKURA["text"] if self.value else YOZAKURA["muted"],
                font=(YOZAKURA_FONT, 10),
            )

        def _update_tooltip(self):
            try:
                self.element.set_tooltip(
                    self.value or "ファイルが選択されていません"
                )
            except Exception:
                pass

        def _on_enter(self, _event):
            self.hover = True
            self.draw()

        def _on_leave(self, _event):
            self.hover = False
            self.draw()

        def set(self, value):
            self.value = str(value or "")
            self._update_tooltip()
            self.draw()

        def resize(self, width):
            """Resize the rounded path surface while preserving its styling."""
            width = max(300, int(width))
            if width == self.width:
                return
            self.width = width
            self.canvas.configure(width=self.width)
            self.draw()


    def polish_yozakura_widgets(window):
        """Apply the flat/rounded-looking details unavailable in PSG themes."""
        import tkinter as tk
        import tkinter.ttk as ttk

        def bind_theme_handler(widget, sequence, callback):
            bindings = getattr(widget, "_rvc_theme_bindings", {})
            if sequence in bindings:
                widget.unbind(sequence, bindings[sequence])
            bindings[sequence] = widget.bind(sequence, callback)
            widget._rvc_theme_bindings = bindings

        window.TKroot.configure(bg=YOZAKURA["bg"])

        style = ttk.Style(window.TKroot)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Yozakura.TCombobox",
            fieldbackground=YOZAKURA["card_alt"],
            background=YOZAKURA["card_alt"],
            foreground=YOZAKURA["text"],
            arrowcolor=YOZAKURA["pink"],
            bordercolor=YOZAKURA["border"],
            lightcolor=YOZAKURA["border"],
            darkcolor=YOZAKURA["border"],
            padding=6,
        )
        style.map(
            "Yozakura.TCombobox",
            fieldbackground=[("readonly", YOZAKURA["card_alt"])],
            foreground=[("readonly", YOZAKURA["text"])],
            selectbackground=[("readonly", YOZAKURA["pink"])],
            selectforeground=[("readonly", YOZAKURA["bg"])],
        )

        from tools.combobox_scroll import protect_combobox_wheel
        for key in ("sg_hostapi", "sg_input_device", "sg_output_device"):
            if key in window.AllKeysDict:
                window[key].Widget.configure(style="Yozakura.TCombobox")
                protect_combobox_wheel(
                    window[key].Widget, window["main_scroll"].TKColFrame.canvas
                )

        def install_custom_vertical_scrollbar(column_element):
            scroll_frame = column_element.Widget
            content_canvas = getattr(scroll_frame, "canvas", None)
            native_scrollbar = getattr(column_element, "vsb", None)
            if content_canvas is None or native_scrollbar is None:
                return
            if hasattr(scroll_frame, "_rvc_scrollbar"):
                scroll_frame._rvc_scrollbar.configure(bg=YOZAKURA["bg"])
                scroll_frame._rvc_scrollbar_redraw()
                return

            native_scrollbar.pack_forget()
            content_canvas.pack_forget()
            scrollbar_width = 26
            track_x = scrollbar_width - 7
            thumb_left = track_x - 4
            thumb_right = track_x + 4
            scrollbar = tk.Canvas(
                scroll_frame,
                width=scrollbar_width,
                bg=YOZAKURA["bg"],
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
            scrollbar.pack(side="right", fill="y")
            content_canvas.pack(side="left", fill="both", expand=True)

            state = {
                "first": 0.0,
                "last": 1.0,
                "thumb": (0, 0),
                "drag_offset": None,
                "hover": False,
            }

            def draw_thumb(first=None, last=None):
                # Embedded native widgets can paint outside their canvas while
                # scrolling on Windows. Keep the fixed header above that row.
                window["window_drag_area"].Widget.master.lift()
                if first is not None and last is not None:
                    state["first"] = float(first)
                    state["last"] = float(last)
                else:
                    state["first"], state["last"] = content_canvas.yview()

                scrollbar.delete("all")
                height = max(scrollbar.winfo_height(), 1)
                top_margin = 5
                bottom_margin = 5
                track_length = max(height - top_margin - bottom_margin, 1)
                visible = max(0.0, min(1.0, state["last"] - state["first"]))
                thumb_length = min(
                    track_length,
                    max(28, int(track_length * visible)),
                )
                travel = max(track_length - thumb_length, 0)
                max_first = max(1.0 - visible, 0.0)
                ratio = state["first"] / max_first if max_first else 0.0
                thumb_top = top_margin + int(travel * ratio)
                thumb_bottom = thumb_top + thumb_length
                state["thumb"] = (thumb_top, thumb_bottom)

                scrollbar.create_line(
                    track_x,
                    top_margin,
                    track_x,
                    height - bottom_margin,
                    fill=YOZAKURA["border"],
                    width=4,
                    capstyle="round",
                )
                thumb_color = (
                    YOZAKURA["pink_light"]
                    if state["hover"]
                    else YOZAKURA["purple"]
                )
                radius = 4
                scrollbar.create_rectangle(
                    thumb_left,
                    thumb_top + radius,
                    thumb_right,
                    thumb_bottom - radius,
                    fill=thumb_color,
                    outline="",
                )
                scrollbar.create_oval(
                    thumb_left,
                    thumb_top,
                    thumb_right,
                    thumb_top + radius * 2,
                    fill=thumb_color,
                    outline="",
                )
                scrollbar.create_oval(
                    thumb_left,
                    thumb_bottom - radius * 2,
                    thumb_right,
                    thumb_bottom,
                    fill=thumb_color,
                    outline="",
                )

            def move_to_pointer(pointer_y, centered=False):
                first, last = content_canvas.yview()
                visible = max(0.0, min(1.0, last - first))
                max_first = max(1.0 - visible, 0.0)
                if max_first <= 0:
                    return
                height = max(scrollbar.winfo_height(), 1)
                track_length = max(height - 10, 1)
                thumb_length = min(track_length, max(28, int(track_length * visible)))
                travel = max(track_length - thumb_length, 1)
                offset = thumb_length / 2 if centered else state["drag_offset"] or 0
                position = max(0.0, min(travel, pointer_y - 5 - offset))
                content_canvas.yview_moveto((position / travel) * max_first)

            def on_press(event):
                thumb_top, thumb_bottom = state["thumb"]
                if thumb_top <= event.y <= thumb_bottom:
                    state["drag_offset"] = event.y - thumb_top
                else:
                    state["drag_offset"] = None
                    move_to_pointer(event.y, centered=True)

            def on_drag(event):
                if state["drag_offset"] is not None:
                    move_to_pointer(event.y)

            def on_release(_event):
                state["drag_offset"] = None

            def on_mousewheel(event):
                units = -int(event.delta / 120) if event.delta else 0
                content_canvas.yview_scroll(units, "units")

            content_canvas.configure(yscrollcommand=draw_thumb)
            scrollbar.bind("<Configure>", lambda _event: draw_thumb())
            scrollbar.bind("<Button-1>", on_press)
            scrollbar.bind("<B1-Motion>", on_drag)
            scrollbar.bind("<ButtonRelease-1>", on_release)
            scrollbar.bind("<MouseWheel>", on_mousewheel)
            scrollbar.bind(
                "<Enter>",
                lambda _event: (state.update(hover=True), draw_thumb()),
            )
            scrollbar.bind(
                "<Leave>",
                lambda _event: (state.update(hover=False), draw_thumb()),
            )
            draw_thumb()

            scroll_frame._rvc_scrollbar = scrollbar
            scroll_frame._rvc_scrollbar_state = state
            scroll_frame._rvc_scrollbar_redraw = draw_thumb

        for key in ("main_scroll", "preset_gallery_scroll"):
            if key in window.AllKeysDict:
                install_custom_vertical_scrollbar(window[key])

        for key in ("pth_path", "index_path"):
            if key in window.AllKeysDict:
                window[key].Widget.configure(
                    relief="flat",
                    bd=0,
                    highlightthickness=0,
                    highlightbackground=YOZAKURA["border"],
                    highlightcolor=YOZAKURA["pink"],
                    insertbackground=YOZAKURA["pink_light"],
                )

        button_colors = {
            "theme_settings": (YOZAKURA["pink_light"], YOZAKURA["card_alt"], YOZAKURA["border"]),
            "start_vc": (YOZAKURA["bg"], YOZAKURA["pink"], YOZAKURA["pink_light"]),
            "stop_vc": (YOZAKURA["text"], YOZAKURA["border"], YOZAKURA["purple"]),
            "save_model_preset": (YOZAKURA["bg"], YOZAKURA["purple"], YOZAKURA["pink_light"]),
            "reload_devices": (YOZAKURA["text"], YOZAKURA["border"], YOZAKURA["purple"]),
            "browse_pth": (YOZAKURA["bg"], YOZAKURA["pink_light"], YOZAKURA["pink"]),
            "browse_index": (YOZAKURA["bg"], YOZAKURA["pink_light"], YOZAKURA["pink"]),
            "browse_preset_image": (YOZAKURA["bg"], YOZAKURA["pink_light"], YOZAKURA["pink"]),
            "clear_preset_image": (YOZAKURA["text"], YOZAKURA["border"], YOZAKURA["purple"]),
            "toggle_audio": (YOZAKURA["text"], YOZAKURA["card_alt"], YOZAKURA["border"]),
            "toggle_voice": (YOZAKURA["text"], YOZAKURA["card_alt"], YOZAKURA["border"]),
            "toggle_engine": (YOZAKURA["text"], YOZAKURA["card_alt"], YOZAKURA["border"]),
            "gallery_prev": (YOZAKURA["text"], YOZAKURA["card_alt"], YOZAKURA["border"]),
            "gallery_next": (YOZAKURA["text"], YOZAKURA["card_alt"], YOZAKURA["border"]),
            "preset_trash": (YOZAKURA["text"], YOZAKURA["card_alt"], YOZAKURA["border"]),
            "export_support_log": (YOZAKURA["text"], YOZAKURA["card_alt"], YOZAKURA["border"]),
        }
        from PIL import Image, ImageDraw, ImageTk

        window.TKroot.update_idletasks()
        for key, colors in button_colors.items():
            if key in window.AllKeysDict:
                widget = window[key].Widget
                minimum_width = 34 if key in ("gallery_prev", "gallery_next") else (64 if key == "theme_settings" else 88)
                width = max(widget.winfo_width(), widget.winfo_reqwidth(), minimum_width)
                height = max(widget.winfo_reqheight(), 36)
                button_background = YOZAKURA["bg"] if key == "theme_settings" else YOZAKURA["card"]

                def rounded_button_image(fill):
                    image = Image.new("RGB", (width, height), button_background)
                    draw = ImageDraw.Draw(image)
                    radius = (
                        min(width, height) // 2
                        if key in ("gallery_prev", "gallery_next")
                        else min(13, height // 2)
                    )
                    draw.rounded_rectangle(
                        (0, 0, width - 1, height - 1),
                        radius=radius,
                        fill=fill,
                    )
                    return ImageTk.PhotoImage(image)

                normal_image = rounded_button_image(colors[1])
                hover_image = rounded_button_image(colors[2])
                widget._yozakura_images = (normal_image, hover_image)
                widget.configure(
                    image=normal_image,
                    compound="center",
                    bg=button_background,
                    fg=colors[0],
                    activebackground=button_background,
                    activeforeground=YOZAKURA["bg"],
                    relief="flat",
                    bd=0,
                    highlightthickness=0,
                    padx=0,
                    pady=0,
                    width=width,
                    height=height,
                    cursor="hand2",
                    font=(YOZAKURA_FONT, 10, "bold"),
                )
                bind_theme_handler(widget,
                    "<Enter>",
                    lambda _event, button=widget, image=hover_image: button.configure(
                        image=image
                    ),
                )
                bind_theme_handler(widget,
                    "<Leave>",
                    lambda _event, button=widget, image=normal_image: button.configure(
                        image=image
                    ),
                )
                if key.startswith("toggle_"):
                    # The original bitmap's width must not become the minimum
                    # width of every card. Keep the request small and redraw
                    # to the allocated width instead.
                    widget.configure(width=1)

                    def redraw_toggle(event, button=widget):
                        size = (max(1, event.width), max(1, event.height))
                        if getattr(button, "_rvc_bitmap_size", None) == size:
                            return
                        button._rvc_bitmap_size = size
                        images = []
                        for fill in (YOZAKURA["card_alt"], YOZAKURA["border"]):
                            bitmap = Image.new("RGB", size, YOZAKURA["card"])
                            ImageDraw.Draw(bitmap).rounded_rectangle(
                                (0, 0, size[0]-1, size[1]-1),
                                radius=min(13, size[1]//2), fill=fill,
                            )
                            images.append(ImageTk.PhotoImage(bitmap))
                        button._yozakura_images = tuple(images)
                        button.configure(image=images[0])

                    widget._rvc_bitmap_size = None
                    bind_theme_handler(widget, "<Configure>", redraw_toggle)
                    from types import SimpleNamespace
                    redraw_toggle(SimpleNamespace(width=widget.winfo_width(), height=widget.winfo_height()))
                    bind_theme_handler(widget, "<Enter>", lambda e, b=widget: b.configure(
                        image=b._yozakura_images[1]))
                    bind_theme_handler(widget, "<Leave>", lambda e, b=widget: b.configure(
                        image=b._yozakura_images[0]))

        for key in (
            "sg_wasapi_exclusive",
            "voicemeeter_enabled",
            "sr_model",
            "sr_device",
            "pm",
            "harvest",
            "crepe",
            "rmvpe",
            "fcpe",
            "I_noise_reduce",
            "O_noise_reduce",
            "use_pv",
            "im",
            "vc",
        ):
            if key in window.AllKeysDict:
                try:
                    window[key].Widget.configure(
                        bg=YOZAKURA["card"],
                        fg=YOZAKURA["text"],
                        activebackground=YOZAKURA["card"],
                        activeforeground=YOZAKURA["pink_light"],
                        selectcolor=YOZAKURA["border"],
                        highlightthickness=0,
                    )
                except Exception:
                    pass

        # Tk frames are rectangular, so mask each corner with an antialiased
        # image. This keeps native widgets while giving every panel true curves.
        card_keys = (
            "card_gallery",
            "card_model_settings",
            "card_transport",
        )
        corner_size = 15
        scale = 4
        base = Image.new(
            "RGB",
            (corner_size * scale, corner_size * scale),
            YOZAKURA["bg"],
        )
        draw = ImageDraw.Draw(base)
        draw.ellipse(
            (0, 0, corner_size * scale * 2, corner_size * scale * 2),
            fill=YOZAKURA["card"],
        )
        base = base.resize((corner_size, corner_size), Image.Resampling.LANCZOS)
        corner_sources = (
            base,
            base.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
            base.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
            base.transpose(Image.Transpose.ROTATE_180),
        )

        for key in card_keys:
            if key not in window.AllKeysDict:
                continue
            frame = window[key].Widget
            images = tuple(ImageTk.PhotoImage(source) for source in corner_sources)
            if hasattr(frame, "_yozakura_corner_labels"):
                for label, image in zip(frame._yozakura_corner_labels, images):
                    label.configure(image=image, bg=YOZAKURA["bg"])
                frame._yozakura_corner_images = images
                continue
            labels = tuple(
                tk.Label(
                    frame,
                    image=image,
                    bg=YOZAKURA["bg"],
                    bd=0,
                    highlightthickness=0,
                )
                for image in images
            )
            frame._yozakura_corner_images = images
            frame._yozakura_corner_labels = labels

            def place_corners(event, corner_labels=labels):
                width = max(event.width, corner_size)
                height = max(event.height, corner_size)
                positions = (
                    (0, 0),
                    (width - corner_size, 0),
                    (0, height - corner_size),
                    (width - corner_size, height - corner_size),
                )
                for label, (x, y) in zip(corner_labels, positions):
                    label.place(x=x, y=y, width=corner_size, height=corner_size)
                    # The frame itself is rectangular. These masks must sit in
                    # front of it; lowering them exposes the original square
                    # frame corners again.
                    label.lift()

            frame.bind("<Configure>", place_corners, add="+")

        metric_corner_size = 10
        metric_scale = 4
        metric_base = Image.new(
            "RGB",
            (metric_corner_size * metric_scale, metric_corner_size * metric_scale),
            YOZAKURA["card"],
        )
        ImageDraw.Draw(metric_base).ellipse(
            (
                0,
                0,
                metric_corner_size * metric_scale * 2,
                metric_corner_size * metric_scale * 2,
            ),
            fill=YOZAKURA["card_alt"],
        )
        metric_base = metric_base.resize(
            (metric_corner_size, metric_corner_size),
            Image.Resampling.LANCZOS,
        )
        metric_corner_sources = (
            metric_base,
            metric_base.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
            metric_base.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
            metric_base.transpose(Image.Transpose.ROTATE_180),
        )
        metric_keys = (
            "snapshot_pitch__tile",
            "snapshot_index__tile",
            "snapshot_mix__tile",
            "snapshot_formant__tile",
            "snapshot_f0__tile",
        )
        for key in metric_keys:
            if key not in window.AllKeysDict:
                continue
            frame = window[key].Widget
            images = tuple(
                ImageTk.PhotoImage(source) for source in metric_corner_sources
            )
            if hasattr(frame, "_yozakura_corner_labels"):
                for label, image in zip(frame._yozakura_corner_labels, images):
                    label.configure(image=image, bg=YOZAKURA["card"])
                frame._yozakura_corner_images = images
                continue
            labels = tuple(
                tk.Label(
                    frame,
                    image=image,
                    bg=YOZAKURA["card"],
                    bd=0,
                    highlightthickness=0,
                )
                for image in images
            )
            frame._yozakura_corner_images = images
            frame._yozakura_corner_labels = labels

            def place_metric_corners(event, corner_labels=labels):
                width = max(event.width, metric_corner_size)
                height = max(event.height, metric_corner_size)
                positions = (
                    (0, 0),
                    (width - metric_corner_size, 0),
                    (0, height - metric_corner_size),
                    (width - metric_corner_size, height - metric_corner_size),
                )
                for label, (x, y) in zip(corner_labels, positions):
                    label.place(
                        x=x,
                        y=y,
                        width=metric_corner_size,
                        height=metric_corner_size,
                    )
                    label.lower()

            frame.bind("<Configure>", place_metric_corners, add="+")

    # device = rvc_for_realtime.config.device
    # device = torch.device(
    #     "cuda"
    #     if torch.cuda.is_available()
    #     else ("mps" if torch.backends.mps.is_available() else "cpu")
    # )
    current_dir = os.getcwd()
    n_cpu = min(cpu_count(), 8)

    class GUIConfig:
        def __init__(self) -> None:
            self.pth_path: str = ""
            self.index_path: str = ""
            self.pitch: int = 0
            self.formant=0.0
            self.sr_type: str = "sr_model"
            self.block_time: float = 0.25  # s
            self.threhold: int = -60
            self.crossfade_time: float = 0.05
            self.extra_time: float = 2.5
            self.I_noise_reduce: bool = False
            self.O_noise_reduce: bool = False
            self.use_pv: bool = False
            self.rms_mix_rate: float = 0.0
            self.index_rate: float = 0.0
            self.n_cpu: int = min(n_cpu, 4)
            self.f0method: str = "fcpe"
            self.sg_hostapi: str = ""
            self.wasapi_exclusive: bool = False
            self.sg_input_device: str = ""
            self.sg_output_device: str = ""

    class GUI:
        def __init__(self) -> None:
            self.gui_config = GUIConfig()
            self.config = Config()
            self.function = "vc"
            self.delay_time = 0
            self.hostapis = None
            self.input_devices = None
            self.output_devices = None
            self.input_devices_indices = None
            self.output_devices_indices = None
            self.stream = None
            self.harvest_pool = HarvestPool()
            self.latest_infer_ms = None
            self._infer_timer = None
            self._displayed_infer_ms = None
            self.current_model_path = ""
            self.loaded_model_preset = False
            from configs.runtime_settings import integration_enabled
            self.voicemeeter_enabled = integration_enabled(current_dir)
            self.audio_error = None
            self.audio_warning = ""
            self.yozakura_sliders = {}
            self.update_devices()
            try:
                self.launcher()
            finally:
                self.stop_stream()
                if hasattr(self, "window"):
                    self.window.close()

        @staticmethod
        def load_expanded_settings_sections():
            state_path = os.path.join(current_dir, "configs", "ui_state.json")
            try:
                with open(state_path, "r", encoding="utf-8") as state_file:
                    state = json.load(state_file)
            except (OSError, ValueError, TypeError):
                return set()
            expanded = state.get("expanded_settings_sections", [])
            if not isinstance(expanded, list):
                return set()
            allowed = {"audio", "voice", "engine"}
            return {name for name in expanded if name in allowed}

        def save_expanded_settings_sections(self):
            state_path = os.path.join(current_dir, "configs", "ui_state.json")
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            state = {
                "schema_version": 1,
                "expanded_settings_sections": sorted(
                    self.expanded_settings_sections
                ),
            }
            temp_path = state_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as state_file:
                json.dump(state, state_file, ensure_ascii=False, indent=2)
                state_file.write("\n")
            os.replace(temp_path, state_path)

        @staticmethod
        def discover_model_presets():
            preset_dir = os.path.join(current_dir, "configs", "model_presets")
            if not os.path.isdir(preset_dir):
                return []

            presets = {}
            for filename in sorted(os.listdir(preset_dir), key=str.lower):
                if not filename.lower().endswith(".json"):
                    continue
                preset_path = os.path.join(preset_dir, filename)
                try:
                    with open(preset_path, "r", encoding="utf-8") as preset_file:
                        preset = json.load(preset_file)
                except (OSError, ValueError, TypeError):
                    continue
                if not isinstance(preset, dict):
                    continue

                model_name = str(
                    preset.get("model_name")
                    or os.path.splitext(filename)[0]
                )
                pth_path = str(preset.get("pth_path", "")).strip().strip('"')
                identity = preset.get("model_identity", "")
                if isinstance(identity, str) and identity.startswith("app:"):
                    pth_path = os.path.join(current_dir, identity[4:])
                if pth_path and not os.path.isabs(pth_path):
                    pth_path = os.path.join(current_dir, pth_path)
                if not pth_path or not os.path.isfile(pth_path):
                    continue

                actual = load_model_preset(pth_path, current_dir)
                if actual is None:
                    continue
                image_path = str(actual.get("image_path", "")).strip().strip('"')
                presets[os.path.normcase(os.path.abspath(pth_path))] = (
                    {
                        "model_name": model_name,
                        "pth_path": os.path.normpath(pth_path),
                        "image_path": image_path,
                    }
                )
            return sorted(presets.values(), key=lambda entry: (entry["model_name"].lower(), entry["pth_path"].lower()))

        def refresh_preset_gallery_selection(self, pth_path):
            if not hasattr(self, "preset_gallery_entries"):
                return
            selected_path = os.path.normcase(os.path.abspath(pth_path or ""))
            for event_key, entry in self.preset_gallery_entries.items():
                active = (
                    os.path.normcase(os.path.abspath(entry["pth_path"]))
                    == selected_path
                )
                if event_key in self.window.AllKeysDict:
                    self.window[event_key].update(
                        image_data=preset_thumbnail_data(
                            entry.get("image_path", ""),
                            entry.get("model_name", ""),
                            active=active,
                            size=getattr(
                                self,
                                "responsive_thumbnail_size",
                                PRESET_THUMBNAIL_SIZE,
                            ),
                        )
                    )

        def preview_preset_gallery_image(self, pth_path, image_path):
            """Preview artwork in the gallery without saving other model settings."""
            clean_model = str(pth_path or "").strip().strip('"')
            if not clean_model or not hasattr(self, "preset_gallery_catalog"):
                return
            selected = os.path.normcase(os.path.abspath(os.path.join(current_dir, clean_model)))
            changed = False
            for entry in self.preset_gallery_catalog:
                identity = os.path.normcase(os.path.abspath(os.path.join(current_dir, entry["pth_path"])))
                if identity == selected:
                    entry["image_path"] = str(image_path or "").strip().strip('"')
                    changed = True
            if changed:
                self.refresh_preset_gallery_selection(self.current_model_path)

        def show_preset_gallery_page(self, page):
            if not hasattr(self, "preset_gallery_catalog"):
                return
            catalog = self.preset_gallery_catalog
            total_pages = max(
                1,
                (len(catalog) + PRESET_GALLERY_PAGE_SIZE - 1)
                // PRESET_GALLERY_PAGE_SIZE,
            )
            self.preset_gallery_page = max(0, min(int(page), total_pages - 1))
            start = self.preset_gallery_page * PRESET_GALLERY_PAGE_SIZE
            page_entries = catalog[start : start + PRESET_GALLERY_PAGE_SIZE]
            self.preset_gallery_entries = {}
            selected_path = os.path.normcase(
                os.path.abspath(self.current_model_path or "")
            )

            for slot in range(PRESET_GALLERY_PAGE_SIZE):
                event_key = "preset_gallery::%d" % slot
                if slot >= len(page_entries):
                    self.window[event_key].update(visible=False)
                    continue
                entry = page_entries[slot]
                self.preset_gallery_entries[event_key] = entry
                self.window[event_key].set_tooltip(
                    "%s\nクリックで切り替え／右クリックで名前変更・削除"
                    % entry.get("model_name", "")
                )
                active = (
                    os.path.normcase(os.path.abspath(entry["pth_path"]))
                    == selected_path
                )
                self.window[event_key].update(
                    image_data=preset_thumbnail_data(
                        entry.get("image_path", ""),
                        entry.get("model_name", ""),
                        active=active,
                        size=getattr(
                            self,
                            "responsive_thumbnail_size",
                            PRESET_THUMBNAIL_SIZE,
                        ),
                    ),
                    visible=True,
                )

            self.window["add_model_preset"].update(
                image_data=preset_add_thumbnail_data(
                    size=getattr(self, "responsive_thumbnail_size", PRESET_THUMBNAIL_SIZE)
                )
            )
            self.window["preset_gallery_page"].update(
                "%d / %d" % (self.preset_gallery_page + 1, total_pages)
            )

        @staticmethod
        def selected_f0method(values):
            return next(
                (
                    method
                    for method in ["pm", "harvest", "crepe", "rmvpe", "fcpe"]
                    if values.get(method)
                ),
                "rmvpe",
            )

        def model_settings_from_values(self, values, pth_path=None):
            return {
                "pth_path": pth_path or values.get("pth_path", ""),
                "index_path": values.get("index_path", ""),
                "image_path": values.get("preset_image_path", ""),
                "pitch": values.get("pitch", 0),
                "formant": values.get("formant", 0.0),
                "index_rate": values.get("index_rate", 0.0),
                "rms_mix_rate": values.get("rms_mix_rate", 0.0),
                "f0method": self.selected_f0method(values),
            }

        def update_preset_status(self, message):
            if hasattr(self, "window"):
                name = model_name_from_path(self.window["pth_path"].get())
                self.preset_inline_text["model_preset_status"] = message
                self.preset_inline_text["selected_preset_name"] = (
                    "選択中：%s" % (name or "モデル未選択"))
                for key in self.preset_inline_text:
                    self.refresh_preset_inline_text(key)

        def refresh_preset_inline_text(self, key):
            """Fit each save-footer label to its line and keep a full tooltip."""
            import tkinter.font as tkfont
            element = self.window[key]
            widget = element.Widget
            full_text = self.preset_inline_text[key]
            font = tkfont.Font(root=widget, font=widget.cget("font"))
            available = max(0, widget.winfo_width() - 6)
            text = full_text
            if font.measure(text) > available:
                while text and font.measure(text + "…") > available:
                    text = text[:-1]
                text += "…"
            element.update(text)
            element.set_tooltip(full_text)

        def update_preset_snapshot(self, values=None):
            if not hasattr(self, "window"):
                return
            values = values or {}

            def current_value(key, default=0.0):
                if key in values:
                    return values[key]
                if key in self.yozakura_sliders:
                    return self.yozakura_sliders[key].value
                return default

            pitch = current_value("pitch", 0)
            formant = current_value("formant", 0.0)
            index_rate = current_value("index_rate", 0.0)
            model_mix = current_value("rms_mix_rate", 0.0)
            f0method = next(
                (
                    method.upper()
                    for method in ["pm", "harvest", "crepe", "rmvpe", "fcpe"]
                    if values.get(method)
                    or (
                        method in self.window.AllKeysDict
                        and self.window[method].get()
                    )
                ),
                "RMVPE",
            )

            snapshot = {
                "snapshot_pitch": "%+d" % int(round(float(pitch))),
                "snapshot_index": "%.2f" % float(index_rate),
                "snapshot_mix": "%.2f" % float(model_mix),
                "snapshot_formant": "%+.2f" % float(formant),
                "snapshot_f0": f0method,
            }
            for key, value in snapshot.items():
                if hasattr(self, "preset_metrics") and key in self.preset_metrics:
                    self.preset_metrics[key].set(value)
                elif key in self.window.AllKeysDict:
                    self.window[key].update(value)

        def refresh_preset_image(self, image_path="", model_name=""):
            if not hasattr(self, "window"):
                return
            clean_path = str(image_path or "").strip().strip('"')
            preview_size = getattr(
                self, "responsive_portrait_size", PRESET_IMAGE_SIZE
            )
            self.window["preset_image_preview"].update(
                data=preset_image_preview_data(
                    clean_path, model_name, size=preview_size
                )
            )
            try:
                self.window["preset_image_preview"].Widget.configure(
                    width=preview_size[0], height=preview_size[1]
                )
            except Exception:
                pass

        def choose_preset_image(self, values):
            from tkinter import filedialog
            from tools.preset_image_editor import edit_preset_image
            source_path = filedialog.askopenfilename(
                parent=self.window.TKroot, title="プリセットに使う画像を選択",
                initialdir=os.path.join(current_dir, "assets", "preset_images"),
                filetypes=[("画像", "*.png *.jpg *.jpeg *.webp *.bmp *.gif")],
            )
            if not source_path:
                return
            model_name = model_name_from_path(values.get("pth_path", ""))
            try:
                image_path = edit_preset_image(sg, self.window, source_path, current_dir, model_name)
            except (OSError, ValueError) as error:
                sg.popup("画像を読み込めませんでした。", str(error), title="画像の確認")
                return
            if image_path is None:
                return
            # Commit UI state only after both editing and file creation succeeded.
            values["preset_image_path"] = image_path
            self.window["preset_image_path"].update(value=image_path)
            self.refresh_preset_image(image_path, model_name)
            self.preview_preset_gallery_image(values.get("pth_path", ""), image_path)
            self.update_preset_status("画像を調整済み · プリセット保存で確定")

        def schedule_responsive_layout(self, event=None):
            """Debounce expensive image redraws while the window is resizing."""
            if not hasattr(self, "window"):
                return
            root = self.window.TKroot
            if event is not None and event.widget is not root:
                return
            pending = getattr(self, "_responsive_after_id", None)
            if pending is not None:
                try:
                    root.after_cancel(pending)
                except Exception:
                    pass
            self._responsive_after_id = root.after(
                110, lambda: self.apply_responsive_layout()
            )

        def center_main_scroll_content(self, event=None):
            """Constrain the embedded frame and keep the horizontal origin fixed."""
            if not hasattr(self, "window"):
                return
            try:
                scroll_frame = self.window["main_scroll"].TKColFrame
                canvas = scroll_frame.canvas
                content_frame = scroll_frame.TKFrame
                canvas_width = (
                    int(event.width)
                    if event is not None and event.widget is canvas
                    else int(canvas.winfo_width())
                )
                content_width = min(1078, max(1, canvas_width))
                content_x = max(0, (canvas_width - content_width) // 2)
                canvas.itemconfigure(scroll_frame.frame_id, width=content_width)
                canvas.coords(scroll_frame.frame_id, content_x, 0)
                canvas.configure(scrollregion=(
                    0, 0, canvas_width, max(1, content_frame.winfo_reqheight())
                ))
                canvas.xview_moveto(0)
                if event is not None:
                    self.schedule_responsive_layout()
            except Exception:
                pass

        def apply_responsive_layout(self, force=False):
            """Scale the wide fixed-size controls to the available viewport."""
            if not hasattr(self, "window"):
                return
            root = self.window.TKroot
            scroll_frame = self.window["main_scroll"].TKColFrame
            window_width = min(1078, scroll_frame.canvas.winfo_width())
            previous_width = getattr(self, "_last_responsive_width", None)
            if (
                not force
                and previous_width is not None
                and window_width == previous_width
            ):
                self._responsive_after_id = None
                return
            self._last_responsive_width = window_width
            self._responsive_after_id = None

            ratio = max(0.0, min(1.0, (window_width - 738) / 340.0))
            portrait_width = int(round(206 + 64 * ratio))
            portrait_height = int(round(portrait_width * 4 / 3))
            show_page = window_width >= 900
            thumbnail_width = min(
                104, max(60, (window_width - (244 if show_page else 196)) // 8)
            )
            thumbnail_height = int(
                round(
                    thumbnail_width
                    * PRESET_THUMBNAIL_SIZE[1]
                    / PRESET_THUMBNAIL_SIZE[0]
                )
            )
            controls_width = window_width - portrait_width - 110
            if "audio_status" in self.window.AllKeysDict:
                self.window["audio_status"].Widget.configure(wraplength=max(300, window_width-100))
            path_width = min(620, max(300, controls_width - 110))
            metric_width = min(98, max(76, (controls_width - 35) // 5))

            portrait_size = (portrait_width, portrait_height)
            thumbnail_size = (thumbnail_width, thumbnail_height)
            portrait_changed = portrait_size != getattr(
                self, "responsive_portrait_size", None
            )
            thumbnails_changed = thumbnail_size != getattr(
                self, "responsive_thumbnail_size", None
            )
            self.responsive_portrait_size = portrait_size
            self.responsive_thumbnail_size = thumbnail_size

            # Keep each gallery position even when the last page has fewer
            # entries. Hiding/repacking buttons in the shared row also moved
            # restored buttons behind the next-page arrow.
            for slot in range(PRESET_GALLERY_PAGE_SIZE):
                frame = self.window["preset_gallery_slot::%d" % slot].Widget
                frame.configure(width=thumbnail_width, height=thumbnail_height)
                frame.pack_propagate(False)

            for display in getattr(self, "path_displays", {}).values():
                display.resize(path_width)
            for metric in getattr(self, "preset_metrics", {}).values():
                metric.resize(metric_width)

            if "preset_gallery_page" in self.window.AllKeysDict:
                self.window["preset_gallery_page"].update(
                    visible=show_page
                )

            compact_transport = window_width < 980
            for key in ("transport_controls", "transport_stats"):
                self.window[key].Widget.pack_configure(
                    side="top" if compact_transport else "left",
                    fill="x", expand=True,
                )

            if portrait_changed or force:
                self.refresh_preset_image(
                    self.window["preset_image_path"].get(),
                    model_name_from_path(self.current_model_path),
                )
            if thumbnails_changed or force:
                self.show_preset_gallery_page(self.preset_gallery_page)

            self.center_main_scroll_content()

        def apply_model_voicemeeter_preset(self, preset):
            try:
                applied = apply_voicemeeter_preset(preset, enabled=getattr(self, "voicemeeter_enabled", False))
                if applied:
                    printt("Voicemeeter model preset applied: %s", applied)
                return True
            except OSError as error:
                printt("Voicemeeter model preset failed: %s", error)
                return False

        def apply_model_preset_to_window(self, preset):
            for key in [
                "index_path",
                "pitch",
                "formant",
                "index_rate",
                "rms_mix_rate",
            ]:
                if key in preset:
                    if key in self.yozakura_sliders:
                        self.yozakura_sliders[key].set(preset[key], notify=False)
                    else:
                        self.window[key].update(value=preset[key])
                    if key == "index_path" and hasattr(self, "path_displays"):
                        self.path_displays["index_path"].set(preset[key])
            if "f0method" in preset:
                selected = preset["f0method"]
                for method in ["pm", "harvest", "crepe", "rmvpe", "fcpe"]:
                    self.window[method].update(value=method == selected)
            image_path = preset.get("image_path", "")
            self.window["preset_image_path"].update(value=image_path)
            self.refresh_preset_image(
                image_path,
                model_name_from_path(self.window["pth_path"].get()),
            )
            self.update_preset_snapshot()

        def save_current_model_preset(self, values, pth_path=None):
            settings = self.model_settings_from_values(values, pth_path=pth_path)
            preset_path = save_model_preset(settings, current_dir)
            model_name = model_name_from_path(settings["pth_path"])
            self.update_preset_status("設定を保存しました")
            if hasattr(self, "preset_gallery_catalog"):
                self.preset_gallery_catalog = self.discover_model_presets()
                self.show_preset_gallery_page(self.preset_gallery_page)
            return preset_path

        def add_model_preset(self, values):
            from tools.preset_import import import_preset
            from tools.preset_import_dialog import choose_preset_files
            selected = choose_preset_files(sg, self.window)
            if selected is None:
                return
            try:
                model_path = import_preset(current_dir, *selected)
                selected_values = dict(values, pth_path=model_path)
                self.window["pth_path"].update(model_path)
                self.handle_model_change(selected_values)
                # An existing model can be imported again with its Index added.
                self.apply_model_preset_to_window(load_model_preset(model_path, current_dir) or {})
                preset = load_model_preset(model_path, current_dir) or {}
                selected_values.update(preset)
                selected_values["preset_image_path"] = preset.get("image_path", "")
                for method in ("pm", "harvest", "crepe", "rmvpe", "fcpe"):
                    selected_values[method] = method == preset.get("f0method", "rmvpe")
                self.persist_session(selected_values)
                self.preset_gallery_catalog = self.discover_model_presets()
                target = next((i for i, entry in enumerate(self.preset_gallery_catalog)
                               if os.path.normcase(entry["pth_path"]) == os.path.normcase(model_path)), 0)
                self.show_preset_gallery_page(target // PRESET_GALLERY_PAGE_SIZE)
                self.update_preset_status("プリセットを追加しました")
            except (OSError, ValueError) as error:
                sg.popup_error("追加できませんでした", str(error), keep_on_top=True)

        def handle_model_change(self, values):
            new_model_path = values.get("pth_path", "").strip()
            from configs.preset_library import is_deleted
            if is_deleted(new_model_path, current_dir):
                self.window["pth_path"].update(self.current_model_path)
                self.path_displays["pth_path"].set(self.current_model_path)
                sg.popup("削除済みのプリセットです。ゴミ箱から復元してください。")
                return
            if hasattr(self, "path_displays"):
                self.path_displays["pth_path"].set(new_model_path)
            if (
                not new_model_path
                or not new_model_path.lower().endswith(".pth")
                or new_model_path == self.current_model_path
            ):
                return

            if self.current_model_path:
                try:
                    self.save_current_model_preset(
                        values, pth_path=self.current_model_path
                    )
                except (OSError, ValueError):
                    pass

            self.stop_stream()
            preset = load_model_preset(new_model_path, current_dir)
            model_name = model_name_from_path(new_model_path)
            if "active_model_name" in self.window.AllKeysDict:
                self.window["active_model_name"].update(
                    model_name or "モデル未選択"
                )
            if preset:
                self.apply_model_preset_to_window(preset)
                banana_applied = self.apply_model_voicemeeter_preset(preset)
                suffix = "" if banana_applied else "（Banana反映失敗）"
                self.update_preset_status("保存した設定を適用済み%s" % suffix)
            else:
                self.apply_model_voicemeeter_preset(None)
                index_path = find_index_for_model(new_model_path, current_dir)
                self.window["index_path"].update(value=index_path)
                if hasattr(self, "path_displays"):
                    self.path_displays["index_path"].set(index_path)
                self.window["preset_image_path"].update(value="")
                self.refresh_preset_image("", model_name)
                self.update_preset_status(
                    "未保存：開始または保存で作成"
                )
            self.current_model_path = new_model_path
            self.refresh_preset_gallery_selection(new_model_path)

        def load(self):
            from configs.runtime_settings import load_runtime_settings, choose_device
            from configs.preset_library import recover_library, is_deleted
            recover_library(current_dir)
            data = load_runtime_settings(current_dir)
            if is_deleted(data.get("pth_path", ""), current_dir):
                data.update(pth_path="", index_path="")
            self.update_devices(hostapi_name=data.get("sg_hostapi"))
            data["sg_hostapi"] = self.selected_hostapi
            defaults = tuple(sd.default.device)
            data["sg_input_device"] = choose_device(
                self.input_devices, self.input_devices_indices, data.get("sg_input_device"), defaults[0])
            data["sg_output_device"] = choose_device(
                self.output_devices, self.output_devices_indices, data.get("sg_output_device"), defaults[1])
            preset = load_model_preset(data.get("pth_path", ""), current_dir)
            if preset:
                data.update(preset)
                self.apply_model_voicemeeter_preset(preset)
                self.loaded_model_preset = True
            data["sr_model"] = data.get("sr_type", "sr_model") == "sr_model"
            data["sr_device"] = not data["sr_model"]
            f0method = data.get("f0method", "rmvpe")
            for method in ["pm", "harvest", "crepe", "rmvpe", "fcpe"]:
                data[method] = f0method == method
            self.current_model_path = data.get("pth_path", "")
            return data

        def launcher(self):
            data = self.load()
            self.config.use_jit = False  # data.get("use_jit", self.config.use_jit)
            apply_yozakura_theme()
            slider_specs = []
            metric_specs = []
            self.responsive_portrait_size = PRESET_IMAGE_SIZE
            self.responsive_thumbnail_size = PRESET_THUMBNAIL_SIZE
            self._responsive_after_id = None
            self._last_responsive_width = None
            self.expanded_settings_sections = (
                self.load_expanded_settings_sections()
            )

            def card(
                title,
                rows,
                key,
                expand_x=True,
                expand_y=False,
                show_title=True,
            ):
                header_rows = (
                    [
                        [
                            sg.Text(
                                "●",
                                font=(YOZAKURA_FONT, 7),
                                text_color=YOZAKURA["pink"],
                                background_color=YOZAKURA["card"],
                                pad=((18, 4), (5, 11)),
                            ),
                            sg.Text(
                                title,
                                key=key + "_title",
                                font=(YOZAKURA_FONT, 10, "bold"),
                                text_color=YOZAKURA["text"],
                                background_color=YOZAKURA["card"],
                                pad=((0, 5), (3, 11)),
                            ),
                        ]
                    ]
                    if show_title
                    else []
                )
                is_primary_card = key in (
                    "card_gallery",
                    "card_model_settings",
                    "card_transport",
                )
                inner_pad = (
                    ((12, 16), (8, 14))
                    if is_primary_card
                    else ((7, 7), (12, 16))
                )
                outer_pad = (
                    ((12, 28), (8, 10))
                    if is_primary_card
                    else ((5, 5), (4, 8))
                )
                inner_content = sg.Column(
                    [*header_rows, *rows],
                    background_color=YOZAKURA["card"],
                    expand_x=True,
                    expand_y=expand_y,
                    pad=inner_pad,
                    element_justification="left",
                    vertical_alignment="top",
                )
                return sg.Frame(
                    "",
                    [[inner_content]],
                    background_color=YOZAKURA["card"],
                    border_width=0,
                    relief=sg.RELIEF_FLAT,
                    pad=outer_pad,
                    expand_x=expand_x,
                    expand_y=expand_y,
                    element_justification="left",
                    vertical_alignment="top",
                    key=key,
                )

            def accordion_toggle(title, key, is_open=False):
                return sg.Button(
                    ("−  " if is_open else "＋  ") + title,
                    key=key,
                    expand_x=True,
                    font=(YOZAKURA_FONT, 10, "bold"),
                    button_color=(YOZAKURA["text"], YOZAKURA["card_alt"]),
                    border_width=0,
                    pad=((6, 6), (10, 8)),
                    tooltip="クリックして設定を開閉します",
                )

            def control_label(text, width=18, tooltip=None):
                return sg.Text(
                    text,
                    size=(width, 1),
                    font=(YOZAKURA_FONT, 10, "bold"),
                    text_color=YOZAKURA["purple"],
                    background_color=YOZAKURA["card"],
                    tooltip=tooltip,
                )

            def modern_slider(
                label,
                slider_range,
                key,
                resolution,
                default,
                tooltip,
            ):
                slider_specs.append(
                    (key, slider_range[0], slider_range[1], resolution, default)
                )
                return [
                    control_label(label, tooltip=tooltip),
                    sg.Canvas(
                        size=(320, 44),
                        key=key + "__canvas",
                        background_color=YOZAKURA["card"],
                        pad=(0, 0),
                        tooltip=tooltip,
                    ),
                    sg.Input(default_text=default, key=key, visible=False),
                ]

            preset_status = (
                "保存した設定を適用済み"
                if self.loaded_model_preset
                else "モデル別プリセットを自動保存・復元"
            )

            initial_model_name = model_name_from_path(data.get("pth_path", ""))
            initial_image_path = data.get("image_path", "")
            initial_model_path = os.path.normcase(
                os.path.abspath(str(data.get("pth_path", "") or ""))
            )

            self.preset_gallery_catalog = self.discover_model_presets()
            self.preset_gallery_page = 0
            self.preset_gallery_entries = {}
            gallery_elements = []
            for slot in range(PRESET_GALLERY_PAGE_SIZE):
                event_key = "preset_gallery::%d" % slot
                entry = (
                    self.preset_gallery_catalog[slot]
                    if slot < len(self.preset_gallery_catalog)
                    else None
                )
                if entry:
                    self.preset_gallery_entries[event_key] = entry
                is_active = bool(
                    entry
                    and os.path.normcase(os.path.abspath(entry["pth_path"]))
                    == initial_model_path
                )
                gallery_button = sg.Button(
                    "",
                    key=event_key,
                    image_data=(
                        preset_thumbnail_data(
                            entry.get("image_path", ""),
                            entry.get("model_name", ""),
                            active=is_active,
                            size=self.responsive_thumbnail_size,
                        )
                        if entry
                        else None
                    ),
                    button_color=(YOZAKURA["card"], YOZAKURA["card"]),
                    border_width=0,
                    pad=(0, 0),
                    visible=bool(entry),
                    tooltip=("%s\nクリックで切り替え／右クリックで名前変更・削除"
                             % entry.get("model_name", "")) if entry else "",
                )
                gallery_elements.append(
                    sg.Column(
                        [[gallery_button]],
                        key="preset_gallery_slot::%d" % slot,
                        pad=((0, 3), (0, 0)),
                        background_color=YOZAKURA["card"],
                        vertical_alignment="center",
                    )
                )

            total_gallery_pages = max(
                1,
                (len(self.preset_gallery_catalog) + PRESET_GALLERY_PAGE_SIZE - 1)
                // PRESET_GALLERY_PAGE_SIZE,
            )

            gallery_card = card(
                i18n("プリセットリスト"),
                [
                    [
                        sg.Button(
                            "‹",
                            key="gallery_prev",
                            size=(2, 3),
                            border_width=0,
                            button_color=(YOZAKURA["muted"], YOZAKURA["card_alt"]),
                            tooltip="前のプリセット一覧を表示します",
                        ),
                        sg.Button(
                            "",
                            key="add_model_preset",
                            image_data=preset_add_thumbnail_data(self.responsive_thumbnail_size),
                            button_color=(YOZAKURA["card"], YOZAKURA["card"]),
                            border_width=0,
                            pad=((0, 3), (0, 0)),
                            tooltip="プリセットを追加\nRVCモデル(.pth)と任意のIndexを選択します",
                        ),
                        *gallery_elements,
                        sg.Button(
                            "›",
                            key="gallery_next",
                            size=(2, 3),
                            border_width=0,
                            button_color=(YOZAKURA["muted"], YOZAKURA["card_alt"]),
                            tooltip="次のプリセット一覧を表示します",
                        ),
                        sg.Text(
                            "1 / %d" % total_gallery_pages,
                            key="preset_gallery_page",
                            size=(5, 1),
                            text_color=YOZAKURA["muted"],
                            background_color=YOZAKURA["card"],
                            justification="center",
                        ),
                    ],
                    [sg.Text("右クリックで名前変更・削除", font=(YOZAKURA_FONT, 9),
                             text_color=YOZAKURA["muted"], background_color=YOZAKURA["card"]),
                     sg.Push(background_color=YOZAKURA["card"]),
                     sg.Button("ゴミ箱", key="preset_trash", size=(13, 1),
                               tooltip="削除したプリセットを30日間保管します。元のモデル・Index・画像は残ります。")],
                ],
                "card_gallery",
            )

            def preset_metric(label, value, key, width=12, tooltip=None):
                metric_specs.append((key, label, value))
                return sg.Canvas(
                    size=(98, 64),
                    key=key + "__canvas",
                    background_color=YOZAKURA["card"],
                    pad=((0, 7), (0, 0)),
                    tooltip=tooltip,
                )

            initial_f0 = str(data.get("f0method", "rmvpe")).upper()

            model_controls = sg.Column(
                [
                    [
                        sg.Text(
                            initial_model_name or "モデル未選択",
                            key="active_model_name",
                            font=(YOZAKURA_FONT, 17, "bold"),
                            text_color=YOZAKURA["pink_light"],
                            background_color=YOZAKURA["card"],
                            pad=((3, 0), (2, 2)),
                        )
                    ],
                    [
                        sg.Text(
                            "選択中のモデル",
                            font=(YOZAKURA_FONT, 8, "bold"),
                            text_color=YOZAKURA["muted"],
                            background_color=YOZAKURA["card"],
                            pad=((3, 0), (0, 15)),
                        )
                    ],
                    [
                        control_label(
                            i18n("RVCモデル（.pth）"),
                            20,
                            "変換する声を収録したモデル本体です。拡張子が.pthのファイルを選びます。",
                        )
                    ],
                    [
                        sg.Input(
                            default_text=data.get("pth_path", ""),
                            key="pth_path",
                            enable_events=True,
                            visible=False,
                        ),
                        sg.Canvas(
                            size=(620, 38),
                            key="pth_path__display",
                            background_color=YOZAKURA["card"],
                            pad=(0, 0),
                            tooltip="RVCモデル本体（.pth）の保存場所",
                        ),
                        sg.FileBrowse(
                            i18n("選択"),
                            key="browse_pth",
                            target="pth_path",
                            initial_folder=os.path.join(os.getcwd(), "assets/weights"),
                            file_types=(("RVC model", "*.pth"),),
                            tooltip="RVCモデル本体（.pth）を選択します",
                        ),
                    ],
                    [
                        control_label(
                            i18n("Indexファイル（.index）"),
                            22,
                            "モデルの声の特徴を補強するファイルです。対応する.indexを選びます。",
                        )
                    ],
                    [
                        sg.Input(
                            default_text=data.get("index_path", ""),
                            key="index_path",
                            enable_events=True,
                            visible=False,
                        ),
                        sg.Canvas(
                            size=(620, 38),
                            key="index_path__display",
                            background_color=YOZAKURA["card"],
                            pad=(0, 0),
                            tooltip="モデルに対応するIndexファイル（.index）の保存場所",
                        ),
                        sg.FileBrowse(
                            i18n("選択"),
                            key="browse_index",
                            target="index_path",
                            initial_folder=os.path.join(os.getcwd(), "logs"),
                            file_types=(("RVC index", "*.index"),),
                            tooltip="モデルに対応するIndexファイル（.index）を選択します",
                        ),
                    ],
                    [
                        sg.Text(
                            "現在のプリセット設定",
                            font=(YOZAKURA_FONT, 8, "bold"),
                            text_color=YOZAKURA["muted"],
                            background_color=YOZAKURA["card"],
                            pad=((3, 0), (18, 7)),
                        )
                    ],
                    [
                        preset_metric(
                            "ピッチ",
                            "%+d" % int(round(float(data.get("pitch", 0)))),
                            "snapshot_pitch",
                            7,
                            "モデルへ適用する声の高さです。",
                        ),
                        preset_metric(
                            "Index",
                            "%.2f" % float(data.get("index_rate", 0)),
                            "snapshot_index",
                            7,
                            "Indexの特徴を反映する強さです。",
                        ),
                        preset_metric(
                            "モデル音量",
                            "%.2f" % float(data.get("rms_mix_rate", 0)),
                            "snapshot_mix",
                            7,
                            "元音声の音量変化を反映する割合です。",
                        ),
                        preset_metric(
                            "声の太さ",
                            "%+.2f" % float(data.get("formant", 0.0)),
                            "snapshot_formant",
                            8,
                            "声の響きの太さを調整する値です。",
                        ),
                        preset_metric(
                            "音程抽出",
                            initial_f0,
                            "snapshot_f0",
                            9,
                            "声の音程を解析する方式です。",
                        ),
                    ],
                ],
                background_color=YOZAKURA["card"],
                expand_x=True,
                vertical_alignment="top",
                pad=(0, 0),
            )

            portrait_panel = sg.Column(
                [
                    [
                        sg.Image(
                            data=preset_image_preview_data(
                                initial_image_path,
                                initial_model_name,
                                size=self.responsive_portrait_size,
                            ),
                            key="preset_image_preview",
                            size=self.responsive_portrait_size,
                            background_color=YOZAKURA["card"],
                            pad=(0, 0),
                        )
                    ],
                    [
                        sg.Push(background_color=YOZAKURA["card"]),
                        sg.Input(
                            default_text=initial_image_path,
                            key="preset_image_path",
                            enable_events=True,
                            visible=False,
                        ),
                        sg.Button(
                            i18n("画像を選択"),
                            key="browse_preset_image",
                            pad=((7, 7), (16, 5)),
                            tooltip="画像を選び、拡大縮小とドラッグで表示範囲を調整します。元画像は変更しません。",
                        ),
                        sg.Button(i18n("解除"), key="clear_preset_image",
                                  pad=((7, 7), (16, 5)),
                                  tooltip="このモデルに設定した画像を解除します。"),
                        sg.Push(background_color=YOZAKURA["card"]),
                    ],
                ],
                background_color=YOZAKURA["card"],
                vertical_alignment="top",
                pad=((4, 14), (0, 0)),
            )

            audio_card = card(
                i18n("オーディオルーティング"),
                [
                    [
                        control_label(
                            i18n("デバイスタイプ"),
                            14,
                            "音声入出力に使うWindowsの方式です。通常はMMEのままで使えます。",
                        ),
                        sg.Combo(
                            self.hostapis,
                            key="sg_hostapi",
                            default_value=data.get("sg_hostapi", ""),
                            enable_events=True,
                            size=(24, 1),
                            readonly=True,
                            tooltip="通常はMMEを選びます。低遅延化したい場合はWASAPIも利用できます。",
                        ),
                        sg.Checkbox(
                            i18n("WASAPI排他モード"),
                            key="sg_wasapi_exclusive",
                            default=data.get("sg_wasapi_exclusive", False),
                            enable_events=True,
                            background_color=YOZAKURA["card"],
                            tooltip="対応機器をRVCが占有して低遅延化します。他アプリと同時利用できない場合があります。",
                        ),
                    ],
                    [
                        control_label(
                            i18n("入力"),
                            14,
                            "変換前の声を受け取るマイクや仮想オーディオデバイスです。",
                        ),
                        sg.Combo(
                            self.input_devices,
                            key="sg_input_device",
                            default_value=data.get("sg_input_device", ""),
                            enable_events=True,
                            size=(61, 1),
                            readonly=True,
                            tooltip="声を入力するマイク、または仮想オーディオデバイスを選びます。",
                        ),
                    ],
                    [
                        control_label(
                            i18n("出力"),
                            14,
                            "変換後の声を送るスピーカーや仮想オーディオデバイスです。",
                        ),
                        sg.Combo(
                            self.output_devices,
                            key="sg_output_device",
                            default_value=data.get("sg_output_device", ""),
                            enable_events=True,
                            size=(61, 1),
                            readonly=True,
                            tooltip="変換した声の出力先を選びます。通話では仮想オーディオデバイスを指定します。",
                        ),
                    ],
                    [
                        sg.Button(i18n("デバイスを再読込"), key="reload_devices", tooltip="接続中の音声デバイス一覧を更新します"),
                        sg.Radio(
                            i18n("モデルSR"),
                            "sr_type",
                            key="sr_model",
                            default=data.get("sr_model", True),
                            enable_events=True,
                            background_color=YOZAKURA["card"],
                            tooltip="モデル本来のサンプルレートで処理します。通常はこちらを推奨します。",
                        ),
                        sg.Radio(
                            i18n("デバイスSR"),
                            "sr_type",
                            key="sr_device",
                            default=data.get("sr_device", False),
                            enable_events=True,
                            background_color=YOZAKURA["card"],
                            tooltip="選択した音声デバイスのサンプルレートに合わせて処理します。",
                        ),
                        sg.Push(background_color=YOZAKURA["card"]),
                        sg.Text(
                            i18n("出力SR"),
                            font=(YOZAKURA_FONT, 9, "bold"),
                            text_color=YOZAKURA["muted"],
                            background_color=YOZAKURA["card"],
                        ),
                        sg.Text(
                            "—",
                            key="sr_stream",
                            font=(YOZAKURA_FONT, 10, "bold"),
                            text_color=YOZAKURA["success"],
                            background_color=YOZAKURA["card"],
                        ),
                    ],
                    [sg.Checkbox(
                        "Bananaの音量・コンプ設定を連携", key="voicemeeter_enabled",
                        default=self.voicemeeter_enabled, enable_events=True,
                        background_color=YOZAKURA["card"],
                        tooltip="ONの場合だけ、モデル切替時にVoicemeeterの設定を変更します。通常はOFFで使えます。",
                    )],
                ],
                "card_audio",
                show_title=False,
            )

            voice_rows = [
                modern_slider(
                    i18n("ノイズゲート"),
                    (-60, 0),
                    "threhold",
                    1,
                    data.get("threhold", -60),
                    "指定した音量より小さい音を無音として扱います。-60でほぼオフです。",
                ),
                modern_slider(
                    i18n("ピッチ"),
                    (-24, 24),
                    "pitch",
                    1,
                    data.get("pitch", 0),
                    "声の高さを半音単位で変更します。男性声から女性声なら+10～+12が目安です。",
                ),
                modern_slider(
                    i18n("声の太さ"),
                    (-2, 2),
                    "formant",
                    0.05,
                    data.get("formant", 0.0),
                    "声の響きを細く、または太く調整します。上げすぎると不自然になります。",
                ),
                modern_slider(
                    i18n("Index Rate"),
                    (0.0, 1.0),
                    "index_rate",
                    0.01,
                    data.get("index_rate", 0),
                    "Indexの特徴を反映する強さです。上げるほどモデルへ寄りますが、ノイズも出やすくなります。",
                ),
                modern_slider(
                    i18n("モデル音量"),
                    (0.0, 1.0),
                    "rms_mix_rate",
                    0.01,
                    data.get("rms_mix_rate", 0),
                    "元音声の音量変化をモデルへ反映する割合です。1.0で最大限追従します。",
                ),
                [
                    control_label(i18n("音程抽出方式"), tooltip="声の音程を解析する方式です。迷った場合はRMVPEを推奨します。"),
                    sg.Radio("PM", "f0method", key="pm", default=data.get("pm", False), enable_events=True, background_color=YOZAKURA["card"], tooltip="軽量ですが、声によっては音程が不安定になります。"),
                    sg.Radio("Harvest", "f0method", key="harvest", default=data.get("harvest", False), enable_events=True, background_color=YOZAKURA["card"], tooltip="CPU処理向けの方式です。Harvestスレッド設定を使用します。"),
                    sg.Radio("CREPE", "f0method", key="crepe", default=data.get("crepe", False), enable_events=True, background_color=YOZAKURA["card"], tooltip="精度重視の音程抽出方式ですが、処理負荷が高めです。"),
                    sg.Radio("RMVPE", "f0method", key="rmvpe", default=data.get("rmvpe", False), enable_events=True, background_color=YOZAKURA["card"], tooltip="品質と安定性のバランスが良い推奨方式です。"),
                    sg.Radio("FCPE", "f0method", key="fcpe", default=data.get("fcpe", True), enable_events=True, background_color=YOZAKURA["card"], tooltip="高速な音程抽出方式です。環境によって相性があります。"),
                ],
            ]

            engine_rows = [
                modern_slider(
                    i18n("ブロック長"),
                    (0.02, 1.5),
                    "block_time",
                    0.01,
                    data.get("block_time", 0.25),
                    "一度に処理する音声の長さです。短いほど低遅延ですが、音切れしやすくなります。",
                ),
                modern_slider(
                    i18n("Harvestスレッド"),
                    (1, n_cpu),
                    "n_cpu",
                    1,
                    data.get("n_cpu", min(self.gui_config.n_cpu, n_cpu)),
                    "Harvest方式で使うCPUスレッド数です。RMVPEなどではほぼ影響しません。",
                ),
                modern_slider(
                    i18n("クロスフェード"),
                    (0.01, 0.15),
                    "crossfade_length",
                    0.01,
                    data.get("crossfade_length", 0.05),
                    "音声ブロックの継ぎ目を滑らかにする長さです。長すぎると遅延が増えます。",
                ),
                modern_slider(
                    i18n("追加推論時間"),
                    (0.05, 5.00),
                    "extra_time",
                    0.01,
                    data.get("extra_time", 2.5),
                    "推論時に前後の音声を参照する長さです。増やすと安定しますが処理が重くなります。",
                ),
                [
                    sg.Checkbox(i18n("入力ノイズ除去"), key="I_noise_reduce", enable_events=True, background_color=YOZAKURA["card"], tooltip="変換前のマイク音声へノイズ除去をかけます。音切れする場合はオフにします。"),
                    sg.Checkbox(i18n("出力ノイズ除去"), key="O_noise_reduce", enable_events=True, background_color=YOZAKURA["card"], tooltip="変換後の音声へノイズ除去をかけます。声が痩せる場合はオフにします。"),
                    sg.Checkbox(i18n("継ぎ目を滑らかにする"), key="use_pv", default=data.get("use_pv", False), enable_events=True, background_color=YOZAKURA["card"], tooltip="フェーズボコーダを使って音声ブロックの継ぎ目を滑らかにします。"),
                ],
            ]

            transport_card = card(
                i18n("変換のON／OFF"),
                [
                    [
                        sg.Column([[
                        sg.Button(
                            "▶  " + i18n("開始"),
                            key="start_vc",
                            size=(15, 2),
                            pad=((16, 7), (5, 14)),
                            tooltip="リアルタイム変換を開始します",
                        ),
                        sg.Button(
                            "■  " + i18n("停止"),
                            key="stop_vc",
                            size=(15, 2),
                            pad=((0, 7), (5, 14)),
                            tooltip="リアルタイム変換を停止します",
                        ),
                        sg.Radio(i18n("入力音を確認"), "function", key="im", default=False, enable_events=True, background_color=YOZAKURA["card"], tooltip="変換前の入力音声をそのまま出力して確認します。"),
                        sg.Radio(i18n("変換音を出力"), "function", key="vc", default=True, enable_events=True, background_color=YOZAKURA["card"], tooltip="RVCで変換した音声を出力します。"),
                        ]], key="transport_controls", pad=(0, 0),
                            background_color=YOZAKURA["card"]),
                        sg.Column([[
                        sg.Push(background_color=YOZAKURA["card"]),
                        sg.Text(i18n("遅延"), font=(YOZAKURA_FONT, 9, "bold"), text_color=YOZAKURA["muted"], background_color=YOZAKURA["card"], tooltip="入力から出力までのおおよその遅延時間です"),
                        sg.Text("0", key="delay_time", font=(YOZAKURA_FONT, 12, "bold"), text_color=YOZAKURA["pink_light"], background_color=YOZAKURA["card"]),
                        sg.Text("ms", text_color=YOZAKURA["muted"], background_color=YOZAKURA["card"]),
                        sg.Text(i18n("推論"), font=(YOZAKURA_FONT, 9, "bold"), text_color=YOZAKURA["muted"], background_color=YOZAKURA["card"], tooltip="モデルが音声変換に使った処理時間です"),
                        sg.Text("0", key="infer_time", font=(YOZAKURA_FONT, 12, "bold"), text_color=YOZAKURA["success"], background_color=YOZAKURA["card"]),
                        sg.Text("ms", text_color=YOZAKURA["muted"], background_color=YOZAKURA["card"]),
                        sg.Canvas(
                            size=(24, 1),
                            background_color=YOZAKURA["card"],
                            pad=(0, 0),
                        ),
                        ]], key="transport_stats", pad=(0, 0), expand_x=True,
                            background_color=YOZAKURA["card"]),
                    ],
                    [sg.Text(getattr(self, "device_error", ""), key="audio_status", size=(1, 2),
                             visible=bool(getattr(self, "device_error", "")),
                             expand_x=True, text_color=YOZAKURA["warning"],
                             background_color=YOZAKURA["card"], pad=((16, 8), (0, 0)))],
                ],
                "card_transport",
            )

            voice_card = card(
                i18n("ボイスデザイン"),
                voice_rows,
                "card_voice",
                show_title=False,
            )
            engine_rows.append([sg.Button("問い合わせ用ログを保存", key="export_support_log",
                                          tooltip="エラーと環境情報をZIPへ保存。自動送信はしません。")])
            engine_card = card(
                i18n("エンジン設定"),
                engine_rows,
                "card_engine",
                show_title=False,
            )

            self.accordion_sections = {
                "toggle_audio": (
                    "section_audio",
                    i18n("オーディオルーティング"),
                    "audio",
                ),
                "toggle_voice": (
                    "section_voice",
                    i18n("ボイスデザイン"),
                    "voice",
                ),
                "toggle_engine": (
                    "section_engine",
                    i18n("エンジン設定"),
                    "engine",
                ),
            }

            # Keep saving and the selected preset visible below every accordion.
            preset_save_footer = sg.Column(
                [[sg.Column([
                    [sg.Button(
                        i18n("プリセットを保存"),
                        key="save_model_preset",
                        size=(18, 1),
                        pad=(0, 0),
                        tooltip="現在のモデル画像と変換設定を、このモデル専用のプリセットとして保存します。",
                    )],
                    [sg.Text(
                        "選択中：%s" % (initial_model_name or "モデル未選択"),
                        key="selected_preset_name", size=(35, 1),
                        font=(YOZAKURA_FONT, 10, "bold"),
                        text_color=YOZAKURA["pink_light"], justification="center",
                        background_color=YOZAKURA["card"], pad=((0, 0), (12, 0)),
                    )],
                    [sg.Text(
                        preset_status, key="model_preset_status", size=(40, 1),
                        font=(YOZAKURA_FONT, 9),
                        text_color=YOZAKURA["muted"], justification="center",
                        background_color=YOZAKURA["card"], pad=((0, 0), (8, 0)),
                    )],
                ], key="preset_save_group", background_color=YOZAKURA["card"],
                    element_justification="center", pad=(0, 0))]],
                key="preset_save_footer",
                background_color=YOZAKURA["card"], expand_x=True,
                element_justification="center",
                pad=((16, 16), (24, 20)),
            )

            model_settings_card = card(
                i18n("モデル設定"),
                [
                    [
                        portrait_panel,
                        model_controls,
                    ],
                    [
                        accordion_toggle(
                            i18n("オーディオルーティング"),
                            "toggle_audio",
                            "audio" in self.expanded_settings_sections,
                        )
                    ],
                    [
                        sg.pin(
                            sg.Column(
                                [[audio_card]],
                                key="section_audio",
                                visible="audio"
                                in self.expanded_settings_sections,
                                background_color=YOZAKURA["card"],
                                expand_x=True,
                                pad=(0, 0),
                            )
                        )
                    ],
                    [
                        accordion_toggle(
                            i18n("ボイスデザイン"),
                            "toggle_voice",
                            "voice" in self.expanded_settings_sections,
                        )
                    ],
                    [
                        sg.pin(
                            sg.Column(
                                [[voice_card]],
                                key="section_voice",
                                visible="voice"
                                in self.expanded_settings_sections,
                                background_color=YOZAKURA["card"],
                                expand_x=True,
                                pad=(0, 0),
                            )
                        )
                    ],
                    [
                        accordion_toggle(
                            i18n("エンジン設定"),
                            "toggle_engine",
                            "engine" in self.expanded_settings_sections,
                        )
                    ],
                    [
                        sg.pin(
                            sg.Column(
                                [[engine_card]],
                                key="section_engine",
                                visible="engine"
                                in self.expanded_settings_sections,
                                background_color=YOZAKURA["card"],
                                expand_x=True,
                                pad=(0, 0),
                            )
                        )
                    ],
                    [preset_save_footer],
                ],
                "card_model_settings",
            )

            header_bar = sg.Column(
                [
                    [
                        sg.Text(
                            "●",
                            key="window_brand_dot",
                            font=(YOZAKURA_FONT, 9),
                            text_color=YOZAKURA["pink"],
                            background_color=YOZAKURA["bg"],
                            pad=((10, 7), (2, 0)),
                        ),
                        sg.Text(
                            "RVC Client",
                            key="window_brand_title",
                            font=(YOZAKURA_FONT, 20, "bold"),
                            text_color=YOZAKURA["pink_light"],
                            background_color=YOZAKURA["bg"],
                            pad=((0, 10), (0, 0)),
                        ),
                        sg.Text(
                            "-Phamu's Edition-",
                            key="window_brand_subtitle",
                            font=(YOZAKURA_FONT, 10),
                            text_color=YOZAKURA["muted"],
                            background_color=YOZAKURA["bg"],
                            pad=((0, 0), (5, 0)),
                        ),
                        sg.Push(background_color=YOZAKURA["bg"]),
                        sg.Button(
                            theme_button_label(), key="theme_settings", size=(7, 1),
                            button_color=(YOZAKURA["pink_light"], YOZAKURA["card_alt"]),
                            border_width=0, pad=((8, 4), (0, 0)),
                            tooltip="クリックで夜桜／ダーク＆オレンジを即時切り替え・自動保存",
                        ),
                        sg.Button(
                            "—",
                            key="window_minimize",
                            font=(YOZAKURA_FONT, 11, "bold"),
                            button_color=(YOZAKURA["muted"], YOZAKURA["bg"]),
                            border_width=0,
                            pad=((12, 3), (0, 0)),
                        ),
                        sg.Button(
                            "□",
                            key="window_maximize",
                            font=(YOZAKURA_FONT, 11),
                            button_color=(YOZAKURA["muted"], YOZAKURA["bg"]),
                            border_width=0,
                            pad=((5, 5), (0, 0)),
                        ),
                        sg.Button(
                            "×",
                            key="window_close",
                            font=(YOZAKURA_FONT, 13),
                            button_color=(YOZAKURA["pink_light"], YOZAKURA["bg"]),
                            border_width=0,
                            pad=((3, 12), (0, 0)),
                        ),
                    ],
                ],
                key="window_drag_area",
                background_color=YOZAKURA["bg"],
                expand_x=True,
                pad=(0, 0),
            )

            content_layout = [
                [gallery_card],
                [model_settings_card],
                [transport_card],
                [
                    sg.Canvas(
                        size=(1, 28),
                        background_color=YOZAKURA["bg"],
                        pad=(0, 0),
                        expand_x=True,
                    )
                ],
            ]
            layout = [
                [header_bar],
                [
                    sg.Column(
                        content_layout,
                        key="main_scroll",
                        size=(1040, 670),
                        scrollable=True,
                        vertical_scroll_only=True,
                        background_color=YOZAKURA["bg"],
                        expand_x=True,
                        expand_y=True,
                        pad=(0, 0),
                        sbar_trough_color=YOZAKURA["card"],
                        sbar_background_color=YOZAKURA["purple"],
                        sbar_arrow_color=YOZAKURA["text"],
                        sbar_frame_color=YOZAKURA["bg"],
                        sbar_width=10,
                        sbar_relief=sg.RELIEF_FLAT,
                    )
                ]
            ]
            self.window = sg.Window(
                "RVC Client -Phamu's Edition-",
                layout=layout,
                finalize=True,
                resizable=True,
                location=(420, 70),
                background_color=YOZAKURA["bg"],
                no_titlebar=True,
                grab_anywhere=False,
                use_custom_titlebar=False,
                use_default_focus=False,
                alpha_channel=(
                    0.0
                    if os.environ.get("RVC_GUI_SMOKE_TEST") == "1"
                    and not os.environ.get("RVC_GUI_PREVIEW_PATH")
                    else 1.0
                ),
            )
            self.preset_inline_text = {
                "selected_preset_name": "選択中：%s" % (initial_model_name or "モデル未選択"),
                "model_preset_status": preset_status,
            }
            for key in self.preset_inline_text:
                self.window[key].Widget.bind(
                    "<Configure>",
                    lambda event, key=key: self.refresh_preset_inline_text(key),
                    add="+",
                )
                self.refresh_preset_inline_text(key)
            self.yozakura_sliders = {
                key: YozakuraSlider(
                    self.window,
                    key + "__canvas",
                    key,
                    minimum,
                    maximum,
                    resolution,
                    default,
                )
                for key, minimum, maximum, resolution, default in slider_specs
            }
            self.preset_metrics = {
                key: PresetMetricTile(
                    self.window,
                    key + "__canvas",
                    label,
                    value,
                )
                for key, label, value in metric_specs
            }
            self.path_displays = {
                "pth_path": RoundedPathDisplay(
                    self.window,
                    "pth_path__display",
                    data.get("pth_path", ""),
                ),
                "index_path": RoundedPathDisplay(
                    self.window,
                    "index_path__display",
                    data.get("index_path", ""),
                ),
            }
            polish_yozakura_widgets(self.window)
            from tools.preset_gallery_scroll import install_gallery_wheel
            install_gallery_wheel(self)
            from tools.preset_management_ui import install_context_menu, refresh_library
            install_context_menu(self, current_dir)
            refresh_library(self, current_dir)
            from tools.transport_indicator import TransportIndicator
            self.transport_indicator = TransportIndicator(self.window)
            self.window.TKroot.minsize(800, 600)
            enable_windows_taskbar(self.window)
            self.window["main_scroll"].TKColFrame.canvas.bind(
                "<Configure>", self.center_main_scroll_content, add="+"
            )
            scroll_frame = self.window["main_scroll"].TKColFrame
            # PySimpleGUI normally uses bbox('all') as the scroll region. With
            # a centered canvas window that also shifts its horizontal origin.
            scroll_frame.set_scrollregion = self.center_main_scroll_content
            scroll_frame.bind("<Configure>", self.center_main_scroll_content)
            scroll_frame.TKFrame.bind(
                "<Configure>", self.center_main_scroll_content, add="+"
            )
            self.window.TKroot.bind(
                "<Configure>", self.schedule_responsive_layout, add="+"
            )
            self.window.TKroot.after_idle(
                lambda: self.apply_responsive_layout(force=True)
            )
            from tools.support_log import attach_tk, environment_info, record
            attach_tk(self.window.TKroot)
            record("Ready environment: " + json.dumps(environment_info(), ensure_ascii=False))
            record("Audio devices: inputs=%d; outputs=%d; host_api=%s" % (
                len(self.input_devices), len(self.output_devices), self.selected_hostapi))
            if getattr(self, "device_error", ""):
                record("Audio device initialization: " + self.device_error)
            print("起動しました。モデルと音声デバイスを選び、「開始」を押してください。", flush=True)
            if os.environ.get("RVC_GUI_SMOKE_TEST") == "1":
                self.window.refresh()
                if os.environ.get("RVC_GUI_LAYOUT_TEST") == "1":
                    from tools.check_gui_layout import check_layout

                    try:
                        check_layout(self)
                        if os.environ.get("RVC_GUI_LIVE_THEME_TEST") == "1":
                            from tools.check_live_theme import check_live_theme
                            check_live_theme(self)
                        if os.environ.get("RVC_GUI_GALLERY_WHEEL_TEST") == "1":
                            from tools.check_gallery_wheel import check_gallery_wheel
                            check_gallery_wheel(self)
                        if os.environ.get("RVC_GUI_TRANSPORT_TEST") == "1":
                            from tools.check_transport_indicator import check_transport_indicator
                            check_transport_indicator(self)
                        if os.environ.get("RVC_GUI_THEME_TEST") == "1":
                            from tools.check_theme_dialog import check_theme_dialog
                            check_theme_dialog(sg, self.window)
                    finally:
                        self.window.close()
                    return
                preview_path = os.environ.get("RVC_GUI_PREVIEW_PATH")
                if preview_path:
                    from PIL import ImageGrab

                    self.window.TKroot.attributes("-topmost", True)
                    self.window.TKroot.deiconify()
                    self.window.TKroot.lift()
                    self.window.TKroot.update()
                    time.sleep(0.2)
                    self.window.TKroot.update_idletasks()
                    x = self.window.TKroot.winfo_rootx()
                    y = self.window.TKroot.winfo_rooty()
                    width = self.window.TKroot.winfo_width()
                    height = self.window.TKroot.winfo_height()
                    ImageGrab.grab((x, y, x + width, y + height)).save(preview_path)
                    print("Yozakura GUI preview: %s" % preview_path)
                print("Yozakura GUI smoke test: OK")
                self.window.close()
                return
            self.event_handler()

        def toggle_window_maximize(self):
            root = self.window.TKroot
            try:
                if sys.platform == "win32" and hasattr(root, "_rvc_toggle_maximize"):
                    root._rvc_toggle_maximize()
                else:
                    root.state("normal" if root.state() == "zoomed" else "zoomed")
            except Exception as error:
                # Window-manager failures must not terminate a running stream.
                printt("Window maximize failed: %s", error)
                self.report_audio_status("ウィンドウサイズを変更できませんでした。もう一度お試しください。")

        def toggle_settings_accordion(self, event):
            _, _, state_name = self.accordion_sections[event]
            if state_name in self.expanded_settings_sections:
                self.expanded_settings_sections.remove(state_name)
            else:
                self.expanded_settings_sections.add(state_name)

            for toggle_key, (
                section_key,
                title,
                section_state_name,
            ) in self.accordion_sections.items():
                is_open = section_state_name in self.expanded_settings_sections
                self.window[section_key].update(visible=is_open)
                self.window[toggle_key].update(
                    ("−  " if is_open else "＋  ") + title
                )
            self.save_expanded_settings_sections()
            self.window.refresh()
            self.window["main_scroll"].contents_changed()

        def toggle_design_theme(self, preference_path=None):
            from tools.live_theme import switch_theme
            try:
                return switch_theme(self, polish_yozakura_widgets, apply_yozakura_theme, preference_path)
            except Exception as error:
                printt("Theme switch failed: %s", error)
                sg.popup_error("テーマを切り替えられませんでした", str(error))

        def report_audio_status(self, message):
            if message and message != getattr(self, "_last_logged_status", ""):
                from tools.support_log import record
                record("Client status: " + str(message))
            self._last_logged_status = message
            if not hasattr(self, "window") or "audio_status" not in getattr(self.window, "AllKeysDict", {}):
                return
            self.window["audio_status"].update(message, visible=bool(message))
            self.window["audio_status"].set_tooltip(message)

        def persist_session(self, values):
            """Persist current UI values without starting/stopping audio or touching Banana."""
            from configs.runtime_settings import load_runtime_settings, write_json, DEFAULT_SETTINGS
            if not values or "pth_path" not in values:
                return
            settings = load_runtime_settings(current_dir)
            settings.update({key: values[key] for key in DEFAULT_SETTINGS if key in values})
            settings["f0method"] = self.selected_f0method(values)
            settings["sr_type"] = "sr_model" if values.get("sr_model", True) else "sr_device"
            settings["use_jit"] = False
            from configs.model_presets import portable_path
            for key in ("pth_path", "index_path"):
                settings[key] = portable_path(settings.get(key, ""), current_dir)
            from configs.preset_library import is_deleted
            if is_deleted(settings.get("pth_path", ""), current_dir):
                settings.update(pth_path="", index_path="")
            try:
                if settings.get("pth_path"):
                    save_model_preset(self.model_settings_from_values(values), current_dir)
                write_json(os.path.join(current_dir, "configs/inuse/config.json"), settings)
            except (OSError, ValueError) as error:
                printt("Settings save failed: %s", error)
                try:
                    self.report_audio_status("設定を保存できませんでした。保存先の権限と空き容量を確認してください。")
                except tk.TclError:
                    pass

        def event_handler(self):
            global flag_vc
            while True:
                event, values = self.window.read()
                values = values or {}
                for key, slider in self.yozakura_sliders.items():
                    values[key] = slider.value
                if event in (sg.WINDOW_CLOSED, "window_close"):
                    self.persist_session(values)
                    return
                if event == "export_support_log":
                    from tools.support_ui import show_support
                    audio = {"host_api": values.get("sg_hostapi", ""),
                             "f0_method": self.selected_f0method(values)}
                    for key in ("pitch", "index_rate"):
                        audio[key] = values.get(key)
                    audio["block_seconds"] = values.get("block_time")
                    for label, attr in (("sample_rate", "samplerate"), ("channels", "channels")):
                        audio[label] = getattr(self.gui_config, attr, None)
                    show_support(sg, self.window, current_dir, audio)
                    continue
                if event in {"preset_management", "preset_trash", "preset_trash_maintenance", "preset_trash_maintenance_done"}:
                    from tools import preset_management_ui as management
                    if event == "preset_management":
                        action, path = values[event]
                        management.perform_action(self, sg, current_dir, action, path, values)
                    elif event == "preset_trash":
                        management.show_trash(self, sg, current_dir)
                    elif event == "preset_trash_maintenance":
                        management.maintenance(self, current_dir)
                    else:
                        management.maintenance_done(self, current_dir, values[event])
                    continue
                if event == "voicemeeter_enabled":
                    from configs.runtime_settings import save_integration
                    try:
                        save_integration(current_dir, values[event])
                        self.voicemeeter_enabled = bool(values[event])
                        if self.voicemeeter_enabled:
                            self.apply_model_voicemeeter_preset(load_model_preset(self.current_model_path, current_dir))
                    except OSError as error:
                        self.window[event].update(self.voicemeeter_enabled)
                        self.report_audio_status("連携設定を保存できませんでした: %s" % error)
                    continue
                if event == "theme_settings":
                    self.toggle_design_theme()
                    continue
                if event == "window_minimize":
                    self.window.minimize()
                    continue
                if event == "window_maximize":
                    self.toggle_window_maximize()
                    continue
                if event in self.accordion_sections:
                    self.toggle_settings_accordion(event)
                    continue
                if event == "gallery_prev":
                    self.show_preset_gallery_page(self.preset_gallery_page - 1)
                    continue
                if event == "gallery_next":
                    self.show_preset_gallery_page(self.preset_gallery_page + 1)
                    continue
                if event == "add_model_preset":
                    if self.stream_is_active():
                        sg.popup("変換を停止してからプリセットを追加してください。")
                    else:
                        self.add_model_preset(values)
                    continue
                if event in self.preset_gallery_entries:
                    selected_path = self.preset_gallery_entries[event]["pth_path"]
                    selected_values = dict(values)
                    selected_values["pth_path"] = selected_path
                    self.window["pth_path"].update(value=selected_path)
                    self.path_displays["pth_path"].set(selected_path)
                    self.handle_model_change(selected_values)
                    continue
                if event == "reload_devices" or event == "sg_hostapi":
                    self.gui_config.sg_hostapi = values["sg_hostapi"]
                    self.update_devices(hostapi_name=values["sg_hostapi"])
                    self.gui_config.sg_hostapi = self.selected_hostapi
                    self.window["sg_hostapi"].Update(values=self.hostapis)
                    self.window["sg_hostapi"].Update(value=self.gui_config.sg_hostapi)
                    if (
                        self.gui_config.sg_input_device not in self.input_devices
                        and len(self.input_devices) > 0
                    ):
                        self.gui_config.sg_input_device = self.input_devices[0]
                    if not self.input_devices:
                        self.gui_config.sg_input_device = ""
                    self.window["sg_input_device"].Update(values=self.input_devices)
                    self.window["sg_input_device"].Update(
                        value=self.gui_config.sg_input_device
                    )
                    if self.gui_config.sg_output_device not in self.output_devices:
                        self.gui_config.sg_output_device = self.output_devices[0] if self.output_devices else ""
                    self.window["sg_output_device"].Update(values=self.output_devices)
                    self.window["sg_output_device"].Update(
                        value=self.gui_config.sg_output_device
                    )
                    self.report_audio_status(self.device_error)
                    continue
                if event in ["pth_path", "browse_pth"]:
                    self.path_displays["pth_path"].set(
                        values.get("pth_path", "")
                    )
                    self.handle_model_change(values)
                    continue
                elif event in ["index_path", "browse_index"]:
                    self.path_displays["index_path"].set(
                        values.get("index_path", "")
                    )
                elif event == "browse_preset_image":
                    self.choose_preset_image(values)
                elif event == "preset_image_path":
                    image_path = values.get("preset_image_path", "")
                    self.refresh_preset_image(
                        image_path,
                        model_name_from_path(values.get("pth_path", "")),
                    )
                    self.preview_preset_gallery_image(values.get("pth_path", ""), image_path)
                    if image_path:
                        self.update_preset_status(
                            "画像選択済み · プリセット保存で確定"
                        )
                elif event == "clear_preset_image":
                    values["preset_image_path"] = ""
                    self.window["preset_image_path"].update(value="")
                    self.refresh_preset_image(
                        "", model_name_from_path(values.get("pth_path", ""))
                    )
                    self.preview_preset_gallery_image(values.get("pth_path", ""), "")
                    self.update_preset_status("画像を解除 · プリセット保存で確定")
                elif event == "save_model_preset":
                    try:
                        self.save_current_model_preset(values)
                        self.current_model_path = values.get("pth_path", "").strip()
                    except (OSError, ValueError) as error:
                        sg.popup(str(error))
                if event == "start_vc" and flag_vc and not self.stream_is_active():
                    self.stop_stream()
                if event == "start_vc" and not flag_vc:
                    if self.set_values(values) == True:
                        printt("cuda_is_available: %s", torch.cuda.is_available())
                        try:
                            from tools.support_log import record
                            record("Conversion start requested: " + json.dumps({
                                key: values.get(key) for key in
                                ("pitch", "index_rate", "block_time", "crossfade_length", "extra_time", "n_cpu")
                            }, ensure_ascii=False))
                            self.start_vc()
                            record("Audio stream started: sample_rate=%s; channels=%s; f0=%s" % (
                                self.gui_config.samplerate, self.gui_config.channels, self.gui_config.f0method))
                        except Exception:
                            self.stop_stream()
                            error_text = traceback.format_exc()
                            from tools.support_log import record
                            record("PLAY start failed\n" + error_text)
                            printt(error_text)
                            sg.popup_error(
                                i18n("PLAY開始に失敗しました"),
                                error_text,
                                keep_on_top=True,
                            )
                            continue
                        settings = {
                            "pth_path": values["pth_path"],
                            "index_path": values["index_path"],
                            "sg_hostapi": values["sg_hostapi"],
                            "sg_wasapi_exclusive": values["sg_wasapi_exclusive"],
                            "sg_input_device": values["sg_input_device"],
                            "sg_output_device": values["sg_output_device"],
                            "sr_type": ["sr_model", "sr_device"][
                                [
                                    values["sr_model"],
                                    values["sr_device"],
                                ].index(True)
                            ],
                            "threhold": values["threhold"],
                            "pitch": values["pitch"],
                            "rms_mix_rate": values["rms_mix_rate"],
                            "index_rate": values["index_rate"],
                            # "device_latency": values["device_latency"],
                            "block_time": values["block_time"],
                            "crossfade_length": values["crossfade_length"],
                            "extra_time": values["extra_time"],
                            "n_cpu": values["n_cpu"],
                            # "use_jit": values["use_jit"],
                            "use_jit": False,
                            "use_pv": values["use_pv"],
                            "f0method": ["pm", "harvest", "crepe", "rmvpe", "fcpe"][
                                [
                                    values["pm"],
                                    values["harvest"],
                                    values["crepe"],
                                    values["rmvpe"],
                                    values["fcpe"],
                                ].index(True)
                            ],
                        }
                        self.persist_session(values)
                        try:
                            self.save_current_model_preset(values)
                        except (OSError, ValueError) as error:
                            self.update_preset_status("テンプレ保存失敗: %s" % error)
                        self.current_model_path = values["pth_path"].strip()
                        if self.stream is not None:
                            self.delay_time = (
                                self.stream.latency[-1]
                                + values["block_time"]
                                + values["crossfade_length"]
                                + 0.01
                            )
                        if values["I_noise_reduce"]:
                            self.delay_time += min(values["crossfade_length"], 0.04)
                        self.window["sr_stream"].update(self.gui_config.samplerate)
                        self.window["delay_time"].update(
                            int(np.round(self.delay_time * 1000))
                        )
                # Parameter hot update
                if event == "threhold":
                    self.gui_config.threhold = values["threhold"]
                elif event == "pitch":
                    self.gui_config.pitch = values["pitch"]
                    if hasattr(self, "rvc"):
                        self.rvc.change_key(values["pitch"])
                    self.update_preset_snapshot(values)
                elif event == "formant":
                    self.gui_config.formant = values["formant"]
                    if hasattr(self, "rvc"):
                        self.rvc.change_formant(values["formant"])
                    self.update_preset_snapshot(values)
                elif event == "index_rate":
                    previous_rate = self.gui_config.index_rate
                    try:
                        if flag_vc and hasattr(self, "rvc"):
                            self.rvc.change_index_rate(values["index_rate"])
                        self.gui_config.index_rate = values["index_rate"]
                    except (OSError, ValueError, RuntimeError) as error:
                        self.yozakura_sliders["index_rate"].set(previous_rate, notify=False)
                        values["index_rate"] = previous_rate
                        self.report_audio_status("Indexを読み込めません。Indexファイルを選び直してください。")
                    self.update_preset_snapshot(values)
                elif event == "rms_mix_rate":
                    self.gui_config.rms_mix_rate = values["rms_mix_rate"]
                    self.update_preset_snapshot(values)
                elif event in ["pm", "harvest", "crepe", "rmvpe", "fcpe"]:
                    if event == "harvest" and flag_vc:
                        self.harvest_pool.ensure(self.gui_config.n_cpu)
                    self.gui_config.f0method = event
                    self.update_preset_snapshot(values)
                elif event == "I_noise_reduce":
                    self.gui_config.I_noise_reduce = values["I_noise_reduce"]
                    if self.stream is not None:
                        self.delay_time += (
                            1 if values["I_noise_reduce"] else -1
                        ) * min(values["crossfade_length"], 0.04)
                        self.window["delay_time"].update(
                            int(np.round(self.delay_time * 1000))
                        )
                elif event == "O_noise_reduce":
                    self.gui_config.O_noise_reduce = values["O_noise_reduce"]
                elif event == "use_pv":
                    self.gui_config.use_pv = values["use_pv"]
                elif event in ["vc", "im"]:
                    self.function = event
                elif event in {"stop_vc", "index_path", "browse_index", "sg_input_device",
                               "sg_output_device", "sg_wasapi_exclusive", "sr_model", "sr_device",
                               "block_time", "crossfade_length", "extra_time", "n_cpu"}:
                    # Other parameters do not support hot update
                    self.stop_stream()
                if event not in {None, "start_vc"}:
                    self.persist_session(values)

        def set_values(self, values):
            from configs.preset_library import is_deleted
            if is_deleted(values.get("pth_path", ""), current_dir):
                sg.popup("削除済みのプリセットです。ゴミ箱から復元してください。")
                return False
            if len(values["pth_path"].strip()) == 0:
                sg.popup(i18n("PTHファイルを選んでください"))
                return False
            if values["index_rate"] > 0 and len(values["index_path"].strip()) == 0:
                sg.popup(i18n("INDEXファイルを選んでください"))
                return False
            if not os.path.isfile(values["pth_path"].strip()):
                sg.popup_error(
                    i18n("PTHファイルが見つかりません"),
                    values["pth_path"],
                    keep_on_top=True,
                )
                return False
            if values["index_rate"] > 0 and not os.path.isfile(values["index_path"].strip()):
                sg.popup_error(
                    i18n("INDEXファイルが見つかりません"),
                    values["index_path"],
                    keep_on_top=True,
                )
                return False
            try:
                self.set_devices(values["sg_input_device"], values["sg_output_device"])
            except (ValueError, IndexError, sd.PortAudioError) as error:
                self.report_audio_status("入力・出力デバイスを再読込して選び直してください。")
                return False
            self.config.use_jit = False  # values["use_jit"]
            # self.device_latency = values["device_latency"]
            self.gui_config.sg_hostapi = values["sg_hostapi"]
            self.gui_config.sg_wasapi_exclusive = values["sg_wasapi_exclusive"]
            self.gui_config.sg_input_device = values["sg_input_device"]
            self.gui_config.sg_output_device = values["sg_output_device"]
            self.gui_config.pth_path = values["pth_path"]
            self.gui_config.index_path = values["index_path"]
            self.gui_config.sr_type = ["sr_model", "sr_device"][
                [
                    values["sr_model"],
                    values["sr_device"],
                ].index(True)
            ]
            self.gui_config.threhold = values["threhold"]
            self.gui_config.pitch = values["pitch"]
            self.gui_config.formant = values["formant"]
            self.gui_config.block_time = values["block_time"]
            self.gui_config.crossfade_time = values["crossfade_length"]
            self.gui_config.extra_time = values["extra_time"]
            self.gui_config.I_noise_reduce = values["I_noise_reduce"]
            self.gui_config.O_noise_reduce = values["O_noise_reduce"]
            self.gui_config.use_pv = values["use_pv"]
            self.gui_config.rms_mix_rate = values["rms_mix_rate"]
            self.gui_config.index_rate = values["index_rate"]
            self.gui_config.n_cpu = values["n_cpu"]
            self.gui_config.f0method = ["pm", "harvest", "crepe", "rmvpe", "fcpe"][
                [
                    values["pm"],
                    values["harvest"],
                    values["crepe"],
                    values["rmvpe"],
                    values["fcpe"],
                ].index(True)
            ]
            return True

        def start_vc(self):
            from infer.lib import rtrvc as rvc_for_realtime

            torch.cuda.empty_cache()
            self.rvc = rvc_for_realtime.RVC(
                self.gui_config.pitch,
                self.gui_config.formant,
                self.gui_config.pth_path,
                self.gui_config.index_path,
                self.gui_config.index_rate,
                self.gui_config.n_cpu,
                None,
                None,
                self.config,
                self.rvc if hasattr(self, "rvc") else None,
                harvest_pool=self.harvest_pool,
            )
            self.gui_config.samplerate = (
                self.rvc.tgt_sr
                if self.gui_config.sr_type == "sr_model"
                else self.get_device_samplerate()
            )
            self.gui_config.channels = self.get_device_channels()
            self.zc = self.gui_config.samplerate // 100
            self.block_frame = (
                int(
                    np.round(
                        self.gui_config.block_time
                        * self.gui_config.samplerate
                        / self.zc
                    )
                )
                * self.zc
            )
            self.block_frame_16k = 160 * self.block_frame // self.zc
            self.crossfade_frame = (
                int(
                    np.round(
                        self.gui_config.crossfade_time
                        * self.gui_config.samplerate
                        / self.zc
                    )
                )
                * self.zc
            )
            self.sola_buffer_frame = min(self.crossfade_frame, 4 * self.zc)
            self.sola_search_frame = self.zc
            self.extra_frame = (
                int(
                    np.round(
                        self.gui_config.extra_time
                        * self.gui_config.samplerate
                        / self.zc
                    )
                )
                * self.zc
            )
            self.input_wav: torch.Tensor = torch.zeros(
                self.extra_frame
                + self.crossfade_frame
                + self.sola_search_frame
                + self.block_frame,
                device=self.config.device,
                dtype=torch.float32,
            )
            self.input_wav_denoise: torch.Tensor = self.input_wav.clone()
            self.input_wav_res: torch.Tensor = torch.zeros(
                160 * self.input_wav.shape[0] // self.zc,
                device=self.config.device,
                dtype=torch.float32,
            )
            self.rms_buffer: np.ndarray = np.zeros(4 * self.zc, dtype="float32")
            self.sola_buffer: torch.Tensor = torch.zeros(
                self.sola_buffer_frame, device=self.config.device, dtype=torch.float32
            )
            self.sola_norm_kernel = torch.ones(
                1, 1, self.sola_buffer_frame, device=self.config.device
            )
            self.nr_buffer: torch.Tensor = self.sola_buffer.clone()
            self.output_buffer: torch.Tensor = self.input_wav.clone()
            self.skip_head = self.extra_frame // self.zc
            self.return_length = (
                self.block_frame + self.sola_buffer_frame + self.sola_search_frame
            ) // self.zc
            self.fade_in_window: torch.Tensor = (
                torch.sin(
                    0.5
                    * np.pi
                    * torch.linspace(
                        0.0,
                        1.0,
                        steps=self.sola_buffer_frame,
                        device=self.config.device,
                        dtype=torch.float32,
                    )
                )
                ** 2
            )
            self.fade_out_window: torch.Tensor = 1 - self.fade_in_window
            self.resampler = tat.Resample(
                orig_freq=self.gui_config.samplerate,
                new_freq=16000,
                dtype=torch.float32,
            ).to(self.config.device)
            if self.rvc.tgt_sr != self.gui_config.samplerate:
                self.resampler2 = tat.Resample(
                    orig_freq=self.rvc.tgt_sr,
                    new_freq=self.gui_config.samplerate,
                    dtype=torch.float32,
                ).to(self.config.device)
            else:
                self.resampler2 = None
            self.tg = TorchGate(
                sr=self.gui_config.samplerate, n_fft=4 * self.zc, prop_decrease=0.9
            ).to(self.config.device)
            if self.gui_config.f0method == "harvest":
                self.harvest_pool.ensure(self.gui_config.n_cpu)
            self.start_stream()

        def stream_is_active(self):
            try:
                return self.stream is not None and bool(self.stream.active)
            except Exception:
                return False  # Unplugged/closed native handles must be restartable too.

        def poll_inference_time(self):
            """Consume the latest numeric sample on Tk's own thread, at 10 Hz."""
            self._infer_timer = None
            if not flag_vc:
                return
            error = getattr(self, "audio_error", None)
            if error or not self.stream_is_active():
                from tools.support_log import record
                record("Audio stream stopped unexpectedly: " + str(error or "inactive device stream"))
                self.stop_stream()
                self.report_audio_status("音声出力が停止しました。デバイスを確認し「開始」で再開できます。" +
                                         ("\n" + str(error)[:180] if error else ""))
                return
            warning = getattr(getattr(self, "rvc", None), "index_warning", "") or getattr(self, "audio_warning", "")
            if warning != getattr(self, "_displayed_audio_warning", ""):
                self.report_audio_status(warning)
                self._displayed_audio_warning = warning
            if hasattr(self, "transport_indicator"):
                self.transport_indicator.set_state(self.function)
            value = self.latest_infer_ms
            if value is not None and value != self._displayed_infer_ms:
                self.window["infer_time"].update(value)
                self._displayed_infer_ms = value
            self._infer_timer = self.window.TKroot.after(
                100, self.poll_inference_time
            )

        def start_stream(self):
            global flag_vc
            if not flag_vc:
                flag_vc = True
                self.audio_error = None
                self.audio_warning = ""
                self._displayed_audio_warning = ""
                self.report_audio_status("")
                if (
                    "WASAPI" in self.gui_config.sg_hostapi
                    and self.gui_config.sg_wasapi_exclusive
                ):
                    extra_settings = sd.WasapiSettings(exclusive=True)
                else:
                    extra_settings = None
                self.stream = sd.Stream(
                    callback=self.audio_callback,
                    blocksize=self.block_frame,
                    samplerate=self.gui_config.samplerate,
                    channels=self.gui_config.channels,
                    dtype="float32",
                    extra_settings=extra_settings,
                )
                self.stream.start()
                self.latest_infer_ms = None
                self.poll_inference_time()

        def stop_stream(self):
            global flag_vc
            flag_vc = False
            if hasattr(self, "transport_indicator"):
                self.transport_indicator.set_state("stopped")
            try:
                if self.stream is not None:
                    stream, self.stream = self.stream, None
                    try:
                        stream.abort()
                    except Exception as error:
                        printt("Audio abort: %s", error)
                    finally:
                        try:
                            stream.close()
                        except Exception as error:
                            printt("Audio close: %s", error)
            finally:
                timer, self._infer_timer = getattr(self, "_infer_timer", None), None
                try:
                    root = getattr(getattr(self, "window", None), "TKroot", None)
                    if timer is not None and root is not None:
                        try:
                            root.after_cancel(timer)
                        except tk.TclError:
                            pass  # Native close may already have destroyed Tk.
                finally:
                    self.harvest_pool.close()

        def audio_callback(
            self, indata: np.ndarray, outdata: np.ndarray, frames, times, status
        ):
            # Callback thread publishes plain data only; all GUI work stays in poll_inference_time.
            try:
                if status:
                    self.audio_warning = "音声処理の遅れ／入力欠けを検出しました。負荷やデバイスを確認してください。"
                self._audio_callback_impl(indata, outdata, frames, times, status)
                if not np.isfinite(outdata).all():
                    raise ValueError("変換結果に無効な数値が含まれています")
            except Exception as error:
                outdata.fill(0)
                self.audio_error = "%s: %s" % (type(error).__name__, error)
                raise sd.CallbackAbort from error

        def _audio_callback_impl(
            self, indata: np.ndarray, outdata: np.ndarray, frames, times, status
        ):
            """
            音频处理
            """
            global flag_vc
            start_time = time.perf_counter()
            indata = librosa.to_mono(indata.T)
            if self.gui_config.threhold > -60:
                indata = np.append(self.rms_buffer, indata)
                rms = librosa.feature.rms(
                    y=indata, frame_length=4 * self.zc, hop_length=self.zc
                )[:, 2:]
                self.rms_buffer[:] = indata[-4 * self.zc :]
                indata = indata[2 * self.zc - self.zc // 2 :]
                db_threhold = (
                    librosa.amplitude_to_db(rms, ref=1.0)[0] < self.gui_config.threhold
                )
                for i in range(db_threhold.shape[0]):
                    if db_threhold[i]:
                        indata[i * self.zc : (i + 1) * self.zc] = 0
                indata = indata[self.zc // 2 :]
            self.input_wav[: -self.block_frame] = self.input_wav[
                self.block_frame :
            ].clone()
            self.input_wav[-indata.shape[0] :] = torch.from_numpy(indata).to(
                self.config.device
            )
            self.input_wav_res[: -self.block_frame_16k] = self.input_wav_res[
                self.block_frame_16k :
            ].clone()
            # input noise reduction and resampling
            if self.gui_config.I_noise_reduce:
                self.input_wav_denoise[: -self.block_frame] = self.input_wav_denoise[
                    self.block_frame :
                ].clone()
                input_wav = self.input_wav[-self.sola_buffer_frame - self.block_frame :]
                input_wav = self.tg(
                    input_wav.unsqueeze(0), self.input_wav.unsqueeze(0)
                ).squeeze(0)
                input_wav[: self.sola_buffer_frame] *= self.fade_in_window
                input_wav[: self.sola_buffer_frame] += (
                    self.nr_buffer * self.fade_out_window
                )
                self.input_wav_denoise[-self.block_frame :] = input_wav[
                    : self.block_frame
                ]
                self.nr_buffer[:] = input_wav[self.block_frame :]
                self.input_wav_res[-self.block_frame_16k - 160 :] = self.resampler(
                    self.input_wav_denoise[-self.block_frame - 2 * self.zc :]
                )[160:]
            else:
                self.input_wav_res[-160 * (indata.shape[0] // self.zc + 1) :] = (
                    self.resampler(self.input_wav[-indata.shape[0] - 2 * self.zc :])[
                        160:
                    ]
                )
            # infer
            if self.function == "vc":
                infer_wav = self.rvc.infer(
                    self.input_wav_res,
                    self.block_frame_16k,
                    self.skip_head,
                    self.return_length,
                    self.gui_config.f0method,
                )
                if self.resampler2 is not None:
                    infer_wav = self.resampler2(infer_wav)
            elif self.gui_config.I_noise_reduce:
                infer_wav = self.input_wav_denoise[self.extra_frame :].clone()
            else:
                infer_wav = self.input_wav[self.extra_frame :].clone()
            # output noise reduction
            if self.gui_config.O_noise_reduce and self.function == "vc":
                self.output_buffer[: -self.block_frame] = self.output_buffer[
                    self.block_frame :
                ].clone()
                self.output_buffer[-self.block_frame :] = infer_wav[-self.block_frame :]
                infer_wav = self.tg(
                    infer_wav.unsqueeze(0), self.output_buffer.unsqueeze(0)
                ).squeeze(0)
            # volume envelop mixing
            if self.gui_config.rms_mix_rate < 1 and self.function == "vc":
                if self.gui_config.I_noise_reduce:
                    input_wav = self.input_wav_denoise[self.extra_frame :]
                else:
                    input_wav = self.input_wav[self.extra_frame :]
                rms1 = librosa.feature.rms(
                    y=input_wav[: infer_wav.shape[0]].cpu().numpy(),
                    frame_length=4 * self.zc,
                    hop_length=self.zc,
                )
                rms1 = torch.from_numpy(rms1).to(self.config.device)
                rms1 = F.interpolate(
                    rms1.unsqueeze(0),
                    size=infer_wav.shape[0] + 1,
                    mode="linear",
                    align_corners=True,
                )[0, 0, :-1]
                rms2 = librosa.feature.rms(
                    y=infer_wav[:].cpu().numpy(),
                    frame_length=4 * self.zc,
                    hop_length=self.zc,
                )
                rms2 = torch.from_numpy(rms2).to(self.config.device)
                rms2 = F.interpolate(
                    rms2.unsqueeze(0),
                    size=infer_wav.shape[0] + 1,
                    mode="linear",
                    align_corners=True,
                )[0, 0, :-1]
                rms2 = torch.max(rms2, torch.zeros_like(rms2) + 1e-3)
                infer_wav *= torch.pow(
                    rms1 / rms2, torch.tensor(1 - self.gui_config.rms_mix_rate)
                )
            # SOLA algorithm from https://github.com/yxlllc/DDSP-SVC
            conv_input = infer_wav[
                None, None, : self.sola_buffer_frame + self.sola_search_frame
            ]
            cor_nom = F.conv1d(conv_input, self.sola_buffer[None, None, :])
            cor_den = torch.sqrt(
                F.conv1d(
                    conv_input**2,
                    self.sola_norm_kernel,
                )
                + 1e-8
            )
            if sys.platform == "darwin":
                _, sola_offset = torch.max(cor_nom[0, 0] / cor_den[0, 0])
                sola_offset = sola_offset.item()
            else:
                sola_offset = torch.argmax(cor_nom[0, 0] / cor_den[0, 0])
            if DEBUG_REALTIME:
                debugt("sola_offset = %d", int(sola_offset))
            infer_wav = infer_wav[sola_offset:]
            if "privateuseone" in str(self.config.device) or not self.gui_config.use_pv:
                infer_wav[: self.sola_buffer_frame] *= self.fade_in_window
                infer_wav[: self.sola_buffer_frame] += (
                    self.sola_buffer * self.fade_out_window
                )
            else:
                infer_wav[: self.sola_buffer_frame] = phase_vocoder(
                    self.sola_buffer,
                    infer_wav[: self.sola_buffer_frame],
                    self.fade_out_window,
                    self.fade_in_window,
                )
            self.sola_buffer[:] = infer_wav[
                self.block_frame : self.block_frame + self.sola_buffer_frame
            ]
            outdata[:] = (
                infer_wav[: self.block_frame]
                .repeat(self.gui_config.channels, 1)
                .t()
                .cpu()
                .numpy()
            )
            total_time = time.perf_counter() - start_time
            if flag_vc:
                self.latest_infer_ms = int(total_time * 1000)
            debugt("Infer time: %.2f", total_time)

        def update_devices(self, hostapi_name=None):
            global flag_vc
            if getattr(self, "stream", None) is not None:
                self.stop_stream()
            flag_vc = False
            self.device_error = ""
            try:
                sd._terminate()
                sd._initialize()
                devices = list(sd.query_devices())
                hostapis = list(sd.query_hostapis())
            except Exception as error:
                devices, hostapis = [], []
                self.device_error = "音声デバイスを取得できません: %s" % error
            self.hostapis = [hostapi["name"] for hostapi in hostapis]
            if hostapi_name not in self.hostapis:
                default_api = int(sd.default.hostapi) if self.hostapis else -1
                hostapi_name = (self.hostapis[default_api] if 0 <= default_api < len(self.hostapis)
                                else self.hostapis[0] if self.hostapis else "")
            self.selected_hostapi = hostapi_name
            api_index = self.hostapis.index(hostapi_name) if hostapi_name in self.hostapis else -1
            inputs = [(index, device["name"]) for index, device in enumerate(devices)
                      if device.get("hostapi") == api_index and device.get("max_input_channels", 0) > 0]
            outputs = [(index, device["name"]) for index, device in enumerate(devices)
                       if device.get("hostapi") == api_index and device.get("max_output_channels", 0) > 0]
            self.input_devices_indices = [index for index, _ in inputs]
            self.output_devices_indices = [index for index, _ in outputs]
            self.input_devices = [name for _, name in inputs]
            self.output_devices = [name for _, name in outputs]
            if not inputs or not outputs:
                self.device_error = self.device_error or "入力または出力デバイスがありません。接続後に再読込してください。"

        def set_devices(self, input_device, output_device):
            """设置输出设备"""
            sd.default.device[0] = self.input_devices_indices[
                self.input_devices.index(input_device)
            ]
            sd.default.device[1] = self.output_devices_indices[
                self.output_devices.index(output_device)
            ]
            printt("Input device: %s:%s", str(sd.default.device[0]), input_device)
            printt("Output device: %s:%s", str(sd.default.device[1]), output_device)

        def get_device_samplerate(self):
            return int(
                sd.query_devices(device=sd.default.device[0])["default_samplerate"]
            )

        def get_device_channels(self):
            max_input_channels = sd.query_devices(device=sd.default.device[0])[
                "max_input_channels"
            ]
            max_output_channels = sd.query_devices(device=sd.default.device[1])[
                "max_output_channels"
            ]
            return min(max_input_channels, max_output_channels, 2)

    gui = GUI()
