"""App appearance preferences, isolated from model and audio configuration."""
import json
import os
from pathlib import Path
import tempfile


NIGHT_CHERRY = {
    # Deep ink-navy base with restrained cherry and wisteria pastels.
    # Keeping the large surfaces dark prevents the soft accents from
    # looking sugary while preserving the Yozakura identity.
    "bg": "#121321",
    "card": "#1c1d30",
    "card_alt": "#27283f",
    "pink": "#d8a7bb",
    "pink_light": "#f0cad7",
    "purple": "#b8aed2",
    "text": "#f5eff4",
    "muted": "#b6adbd",
    "border": "#41405a",
    "success": "#a9d2be",
    "warning": "#e3bea8",
    "art_top": "#12122a",
    "art_bottom": "#261c46",
    "art_orb": "#45394e",
    "art_orb_alt": "#2b2653",
}
DARK_ORANGE = {
    "bg": "#1d1c1a",
    "card": "#282725",
    "card_alt": "#33312e",
    "pink": "#de7d54",       # Legacy role name: primary accent.
    "pink_light": "#f3a06d", # Legacy role name: bright accent.
    "purple": "#ce8b64",     # Secondary accent / scrollbar.
    "text": "#f2ede5",
    "muted": "#bcb3a8",
    "border": "#555049",
    "success": "#b1c5a5",
    "warning": "#e0bb80",
    "art_top": "#25221f",
    "art_bottom": "#3c3028",
    "art_orb": "#584035",
    "art_orb_alt": "#433a30",
}
THEMES = {"yozakura": NIGHT_CHERRY, "dark_orange": DARK_ORANGE}
THEME_NAMES = {"yozakura": "夜桜", "dark_orange": "ダーク＆オレンジ"}
THEME_SETTINGS_PATH = Path(__file__).resolve().parents[1] / "configs/theme_settings.json"


def load_theme_preference(path=None):
    try:
        data = json.loads(Path(path or THEME_SETTINGS_PATH).read_text(encoding="utf-8"))
        selected = data.get("theme") if isinstance(data, dict) else None
        return selected if isinstance(selected, str) and selected in THEMES else "yozakura"
    except (OSError, ValueError, TypeError):
        return "yozakura"


def save_theme_preference(theme_id, path=None):
    if theme_id not in THEMES:
        raise ValueError("Unknown theme")
    target = Path(path or THEME_SETTINGS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Replace only the dedicated appearance file; never touch voice presets.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                     prefix=target.name + ".", suffix=".tmp", delete=False) as handle:
        json.dump({"schema_version": 1, "theme": theme_id}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(handle.name, target)


ACTIVE_THEME_ID = os.environ.get("RVC_GUI_THEME") or load_theme_preference()
if ACTIVE_THEME_ID not in THEMES:
    ACTIVE_THEME_ID = "yozakura"
# Keep the historical import name to avoid changing audio-adjacent GUI code.
YOZAKURA = dict(THEMES[ACTIVE_THEME_ID])


def activate_theme(theme_id):
    """Mutate the shared palette so existing widget renderers see the new colors."""
    global ACTIVE_THEME_ID
    if theme_id not in THEMES:
        raise ValueError("Unknown theme")
    YOZAKURA.clear()
    YOZAKURA.update(THEMES[theme_id])
    ACTIVE_THEME_ID = theme_id


def theme_button_label():
    return "夜桜" if ACTIVE_THEME_ID == "yozakura" else "オレンジ"


YOZAKURA_FONT = "Noto Sans JP"
PRESET_IMAGE_SIZE = (270, 360)
PRESET_THUMBNAIL_SIZE = (104, 122)
# Seven models plus the always-visible add tile occupy eight gallery columns.
PRESET_GALLERY_PAGE_SIZE = 7
