"""Portable app icon paths and Windows taskbar identity (no audio dependencies)."""
from pathlib import Path
import sys

APP_ID = "PhamuStudio.RVCClient.PhamuEdition"
BRANDING_DIR = Path(__file__).resolve().parents[1] / "assets" / "branding"
APP_ICON = BRANDING_DIR / ("phamu-client.ico" if sys.platform == "win32" else "phamu-client.png")


def configure_windows_app_id():
    """Keep the client separate from other Python apps in the Windows taskbar."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        result = set_app_id(APP_ID)
        if result != 0:
            raise OSError("SetCurrentProcessExplicitAppUserModelID: %s" % result)
        return True
    except (AttributeError, OSError) as error:
        # Branding must never prevent voice conversion from starting.
        print("Windows app identity unavailable: %s" % error)
        return False


def app_icon_path():
    """Let PySimpleGUI use its fallback if the optional asset is missing."""
    return str(APP_ICON) if APP_ICON.is_file() else None
