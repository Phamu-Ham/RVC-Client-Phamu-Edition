"""Repaint the existing Tk UI without recreating windows or audio objects."""
import tkinter as tk
from tools import yozakura_theme as theme
from tools.preset_artwork import preset_image_preview_data, preset_thumbnail_data


def repaint_widgets(root, previous):
    mapping = {value.lower(): theme.YOZAKURA[key] for key, value in previous.items()}
    pending = [root]
    color_options = (
        "background", "foreground", "activebackground", "activeforeground",
        "disabledforeground", "highlightbackground", "highlightcolor",
        "insertbackground", "selectbackground", "selectforeground", "selectcolor",
        "troughcolor", "readonlybackground", "disabledbackground",
    )
    while pending:
        widget = pending.pop()
        pending.extend(widget.winfo_children())
        keys = widget.keys()
        updates = {}
        for option in color_options:
            if option in keys:
                old = str(widget.cget(option)).lower()
                if old in mapping:
                    updates[option] = mapping[old]
        if updates:
            widget.configure(**updates)
        if isinstance(widget, tk.Canvas):
            for item in widget.find_all():
                options = widget.itemconfigure(item)
                updates = {}
                for option in ("fill", "outline", "activefill", "activeoutline"):
                    if option in options:
                        old = str(options[option][-1]).lower()
                        if old in mapping:
                            updates[option] = mapping[old]
                if updates:
                    widget.itemconfigure(item, **updates)


def apply_live_theme(gui, theme_id, polish, register):
    previous = dict(theme.YOZAKURA)
    theme.activate_theme(theme_id)
    register()
    repaint_widgets(gui.window.TKroot, previous)
    polish(gui.window)
    for slider in gui.yozakura_sliders.values():
        slider._draw()
    for tile in gui.preset_metrics.values():
        tile.draw()
    for path in gui.path_displays.values():
        path.draw()
    preset_image_preview_data.cache_clear()
    preset_thumbnail_data.cache_clear()
    gui.refresh_preset_image(gui.window["preset_image_path"].get(),
                             gui.window["active_model_name"].get())
    gui.show_preset_gallery_page(gui.preset_gallery_page)
    gui.transport_indicator.refresh_theme()
    gui.window["theme_settings"].update(theme.theme_button_label())


def switch_theme(gui, polish, register, preference_path=None):
    original = theme.ACTIVE_THEME_ID
    selected = "dark_orange" if original == "yozakura" else "yozakura"
    try:
        apply_live_theme(gui, selected, polish, register)
        theme.save_theme_preference(selected, preference_path)
    except Exception:
        apply_live_theme(gui, original, polish, register)
        raise
    return selected
