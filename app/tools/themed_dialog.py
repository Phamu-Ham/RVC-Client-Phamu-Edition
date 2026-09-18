"""Frameless auxiliary dialogs and a canvas scrollbar, without native hooks."""
import tkinter as tk
from PIL import Image, ImageColor, ImageDraw, ImageTk

from tools.preset_context_menu import _place_and_round, _work_area
from tools.yozakura_theme import YOZAKURA, YOZAKURA_FONT


class DialogOutline:
    """Paint only the outer margin, leaving all dialog controls unobstructed."""
    def __init__(self, root):
        background = ImageColor.getrgb(YOZAKURA["card"])
        accent = ImageColor.getrgb(YOZAKURA["pink_light"])
        self.color = "#%02x%02x%02x" % tuple(
            round(bg + (fg - bg) * 0.35) for bg, fg in zip(background, accent)
        )
        self.edges = [tk.Canvas(root, width=1, height=1, bd=0,
                               highlightthickness=0, takefocus=False,
                               background=YOZAKURA["card"]) for _ in range(4)]
        self.size = None

    def draw(self, width, height):
        if self.size == (width, height) or min(width, height) < 24:
            return
        self.size = (width, height)
        scale, margin = 4, 10
        image = Image.new("RGB", (width * scale, height * scale), YOZAKURA["card"])
        ImageDraw.Draw(image).rounded_rectangle(
            (scale, scale, width * scale - scale - 1, height * scale - scale - 1),
            radius=7 * scale, outline=self.color, width=scale,
        )
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        boxes = ((0, 0, width, margin), (0, height - margin, width, height),
                 (0, margin, margin, height - margin),
                 (width - margin, margin, width, height - margin))
        for canvas, (left, top, right, bottom) in zip(self.edges, boxes):
            canvas._outline_image = ImageTk.PhotoImage(
                image.crop((left, top, right, bottom)), master=canvas)
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=canvas._outline_image)
            # PSG's root has internal margins; paint relative to the real edge.
            canvas.place(x=left, y=top, width=right - left, height=bottom - top,
                         bordermode="ignore")
            # Canvas.lift() raises drawing items, not the widget itself.
            canvas.tk.call("raise", canvas._w)


def set_button_disabled(element, disabled, width=90):
    """Keep true disabled behavior while avoiding Tk's stippled image rendering."""
    from tools.dialog_widgets import rounded_image
    button = element.Widget
    cover = getattr(button, "_disabled_cover", None)
    if cover is not None:
        cover.destroy()
        button._disabled_cover = None
    element.update(disabled=disabled)
    if not disabled:
        return
    cover = tk.Canvas(button, width=width, height=38, bg=YOZAKURA["card"], bd=0, highlightthickness=0)
    cover.place(x=0, y=0, width=width, height=38)
    cover._image = rounded_image(cover, width, 38, YOZAKURA["card_alt"])
    cover.create_image(0, 0, anchor="nw", image=cover._image)
    cover.create_text(width / 2, 19, text=button.cget("text"), fill=YOZAKURA["muted"], font=(YOZAKURA_FONT, 10))
    button._disabled_cover = cover


def style_dialog(dialog, close_key):
    root = dialog.TKroot
    root._dialog_outline = DialogOutline(root)
    root.bind("<Escape>", lambda _e: dialog.write_event_value(close_key, None))
    root.protocol("WM_DELETE_WINDOW", lambda: dialog.write_event_value(close_key, None))
    drag = {}
    root._dialog_drag_state = drag

    def press(event):
        drag.update(x=event.x_root - root.winfo_rootx(), y=event.y_root - root.winfo_rooty())
        return "break"

    def move(event):
        if drag:
            x, y = event.x_root - drag["x"], event.y_root - drag["y"]
            drag["target"] = (x, y)
            root.geometry("%+d%+d" % (x, y))
            return "break"

    for key in ("_dialog_header", "_dialog_title"):
        widget = dialog[key].Widget
        widget.bind("<ButtonPress-1>", press, add="+")
        widget.configure(cursor="fleur")
    root.bind("<B1-Motion>", move, add="+")
    root.bind("<ButtonRelease-1>", lambda _e: drag.clear(), add="+")
    root.update_idletasks()
    width, height = root.winfo_width(), root.winfo_height()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    left, top, right, bottom = _work_area(root, x, y)
    x, y = max(left, min(x, right - width)), max(top, min(y, bottom - height))
    root.geometry("%+d%+d" % (x, y))

    def round_after_layout(event=None):
        if event is None or event.widget is root:
            size = (root.winfo_width(), root.winfo_height())
            if getattr(root, "_dialog_region_size", None) == size:
                return
            root._dialog_region_size = size
            root._dialog_outline.draw(*size)
            _place_and_round(root, root.winfo_rootx(), root.winfo_rooty(),
                             *size, place=False)
    root.bind("<Configure>", round_after_layout, add="+")
    root.after_idle(round_after_layout)


class ThemedListScrollbar:
    def __init__(self, listbox):
        self.listbox = listbox
        self.offset = None
        self.first, self.last = 0.0, 1.0
        self.wheel = 0
        parent = listbox.master
        parent.configure(background=YOZAKURA["card_alt"])
        self.original = []
        for widget in parent.winfo_children():
            if widget.winfo_class() in ("Scrollbar", "TScrollbar"):
                self.original.append(widget)
                if widget.winfo_manager() == "pack":
                    widget.pack_forget()
                elif widget.winfo_manager() == "grid":
                    widget.grid_remove()
        self.canvas = tk.Canvas(parent, width=12, height=1, bd=0, highlightthickness=0, background=YOZAKURA["card_alt"])
        if listbox.winfo_manager() == "pack":
            self.canvas.pack(side="right", fill="y", before=listbox)
        else:
            self.canvas.grid(row=0, column=1, sticky="ns")
        listbox.configure(yscrollcommand=self.set)
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: setattr(self, "offset", None))
        self.canvas.bind("<MouseWheel>", self.scroll)
        self.set(*listbox.yview())
        listbox._themed_scrollbar = self

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.draw()

    def geometry(self):
        height = max(1, self.canvas.winfo_height() - 12)
        length = min(height, max(24, height * (self.last - self.first)))
        travel = max(0, height - length)
        position = travel * self.first / max(0.00001, 1 - (self.last - self.first))
        return 6 + position, length, travel

    def draw(self):
        self.canvas.delete("all")
        if self.last - self.first >= 1:
            return
        top, length, _ = self.geometry()
        self.canvas.create_line(6, top + 3, 6, top + length - 3, width=6,
                                fill=YOZAKURA["purple"], capstyle="round", tags="thumb")

    def press(self, event):
        if self.last - self.first >= 1:
            return
        top, length, _ = self.geometry()
        self.offset = event.y - top if top <= event.y <= top + length else length / 2
        self.drag(event)

    def drag(self, event):
        if self.offset is None:
            return
        _, _, travel = self.geometry()
        fraction = max(0, min(1, (event.y - self.offset - 6) / max(1, travel)))
        self.listbox.yview_moveto(fraction * (1 - (self.last - self.first)))

    def scroll(self, event):
        self.wheel += event.delta
        steps = int(self.wheel / 120)
        self.wheel -= steps * 120
        if steps:
            self.listbox.yview_scroll(-steps * 3, "units")
        return "break"
