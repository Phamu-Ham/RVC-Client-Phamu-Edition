"""Local wheel paging: never change the selected preset or audio settings."""
import time
from tools.yozakura_theme import PRESET_GALLERY_PAGE_SIZE


def install_gallery_wheel(gui):
    frame = gui.window["card_gallery"].Widget
    if hasattr(frame, "_rvc_gallery_wheel"):
        return
    state = {"remainder": 0, "time": 0.0}

    def on_wheel(event):
        now = time.monotonic()
        number = getattr(event, "num", None)
        delta = (120 if number == 4 else -120 if number == 5
                 else getattr(event, "delta", 0))
        # Accumulate high-resolution wheels; don't carry a partial notch across
        # separate gestures or a reversal of direction.
        if now - state["time"] > 0.5 or delta * state["remainder"] < 0:
            state["remainder"] = 0
        state["time"] = now
        state["remainder"] += delta
        steps = int(state["remainder"] / 120)
        state["remainder"] -= steps * 120
        if steps:
            pages = max(1, (len(gui.preset_gallery_catalog) + PRESET_GALLERY_PAGE_SIZE - 1)
                        // PRESET_GALLERY_PAGE_SIZE)
            target = max(0, min(pages - 1, gui.preset_gallery_page - steps))
            if target != gui.preset_gallery_page:
                gui.show_preset_gallery_page(target)
        # Even at the ends, don't unexpectedly scroll the main page instead.
        return "break"

    # Buttons, labels and the space between them all belong to this one card.
    # Widget-local bindings stop propagation before PySimpleGUI's global scroll
    # handler. No bind_all/unbind_all, so other widgets and dialogs are untouched.
    pending = [frame]
    while pending:
        widget = pending.pop()
        pending.extend(widget.winfo_children())
        for sequence in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, on_wheel)
    frame._rvc_gallery_wheel = on_wheel
    frame._rvc_gallery_wheel_state = state
