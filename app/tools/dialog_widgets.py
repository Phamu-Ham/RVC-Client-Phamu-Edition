"""Small rounded Tk surfaces for auxiliary dialogs; no audio dependencies."""
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from tools.yozakura_theme import YOZAKURA, YOZAKURA_FONT


def rounded_image(widget, width, height, fill, outline=None, radius=12):
    scale = 4
    image = Image.new("RGB", (width * scale, height * scale), YOZAKURA["card"])
    ImageDraw.Draw(image).rounded_rectangle(
        (2, 2, width * scale - 3, height * scale - 3),
        radius=radius * scale, fill=fill, outline=outline, width=4,
    )
    return ImageTk.PhotoImage(image.resize((width, height), Image.Resampling.LANCZOS), master=widget)


def style_button(element, primary=False, width=90):
    button = element.Widget
    fill = YOZAKURA["pink_light"] if primary else YOZAKURA["card_alt"]
    hover = YOZAKURA["pink"] if primary else YOZAKURA["border"]
    images = tuple(rounded_image(button, width, 38, color) for color in (fill, hover))
    button._rounded_images = images
    button.configure(image=images[0], compound="center", width=width, height=38,
                     padx=0, pady=0, bd=0, highlightthickness=0, relief="flat",
                     background=YOZAKURA["card"], activebackground=YOZAKURA["card"],
                     foreground=YOZAKURA["bg"] if primary else YOZAKURA["text"],
                     activeforeground=YOZAKURA["bg"] if primary else YOZAKURA["text"],
                     font=(YOZAKURA_FONT, 10), cursor="hand2")
    button.bind("<Enter>", lambda _event: button.configure(image=images[1]), add="+")
    button.bind("<Leave>", lambda _event: button.configure(image=images[0]), add="+")


def rounded_entry(dialog, key, width=432):
    """Use the PSG input's StringVar so browsing, typing and drops stay in sync."""
    canvas = dialog[key + "_surface"].TKCanvas
    canvas.configure(width=width, height=44, bg=YOZAKURA["card"], bd=0, highlightthickness=0)
    images = tuple(rounded_image(canvas, width, 44, YOZAKURA["card_alt"], color)
                   for color in (YOZAKURA["border"], YOZAKURA["pink"]))
    canvas._rounded_images = images
    surface = canvas.create_image(0, 0, image=images[0], anchor="nw")
    entry = tk.Entry(canvas, textvariable=dialog[key].TKStringVar,
                     font=(YOZAKURA_FONT, 10), relief="flat", bd=0, highlightthickness=0,
                     bg=YOZAKURA["card_alt"], fg=YOZAKURA["text"],
                     insertbackground=YOZAKURA["pink_light"],
                     selectbackground=YOZAKURA["pink"], selectforeground=YOZAKURA["bg"])
    canvas.create_window(13, 22, window=entry, anchor="w", width=width-26, height=26)
    entry.bind("<FocusIn>", lambda _event: canvas.itemconfigure(surface, image=images[1]))
    entry.bind("<FocusOut>", lambda _event: canvas.itemconfigure(surface, image=images[0]))
    canvas.bind("<Button-1>", lambda _event: entry.focus_set())
    return entry


class DropSurface:
    def __init__(self, canvas, width=536):
        self.canvas = canvas
        canvas.configure(width=width, height=92, bg=YOZAKURA["card"], bd=0, highlightthickness=0)
        self.images = tuple(rounded_image(canvas, width, 92, YOZAKURA["card_alt"], color, 16)
                            for color in (YOZAKURA["border"], YOZAKURA["pink"]))
        self.surface = canvas.create_image(0, 0, image=self.images[0], anchor="nw")
        self.heading = canvas.create_text(width//2, 32, text="ここにファイルをドロップ",
                                          font=(YOZAKURA_FONT, 12, "bold"), fill=YOZAKURA["pink_light"])
        self.caption = canvas.create_text(width//2, 61, text="PTH と Index を自動で振り分けます",
                                          font=(YOZAKURA_FONT, 10), fill=YOZAKURA["muted"])

    def highlight(self, active):
        self.canvas.itemconfigure(self.surface, image=self.images[bool(active)])

    def unavailable(self):
        self.canvas.itemconfigure(self.heading, text="「選択」からファイルを指定してください")
        self.canvas.itemconfigure(self.caption, text="この環境ではドラッグ＆ドロップを利用できません")
