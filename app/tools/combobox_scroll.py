"""Keep page scrolling from silently changing audio-device selections."""
import time


def protect_combobox_wheel(combo, scroll_canvas):
    """Guard this widget only; the opened dropdown keeps its normal bindings."""
    if hasattr(combo, "_rvc_wheel_guard"):
        return
    state = {"remainder": 0, "time": 0.0}

    def on_wheel(event):
        # A posted dropdown is a separate Listbox. Do not move the page if a
        # wheel event happens to land on its owning combobox while it is open.
        if combo.instate(["pressed"]):
            state["remainder"] = 0
            return "break"
        number = getattr(event, "num", None)
        delta = (120 if number == 4 else -120 if number == 5
                 else getattr(event, "delta", 0))
        now = time.monotonic()
        if now - state["time"] > 0.5 or delta * state["remainder"] < 0:
            state["remainder"] = 0
        state["time"] = now
        state["remainder"] += delta
        steps = int(state["remainder"] / 120)
        state["remainder"] -= steps * 120
        if steps:
            scroll_canvas.yview_scroll(-steps, "units")
        # Stop before TCombobox changes the value / emits ComboboxSelected,
        # and before PySimpleGUI's global handler scrolls the page a second time.
        return "break"

    for sequence in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>"):
        combo.bind(sequence, on_wheel, add="+")
    combo._rvc_wheel_guard = on_wheel
