import ctypes
import os
import sys
import time


DEFAULT_VOICEMEETER_STRIP = {
    "strip_index": 0,
    "parameters": {
        "Comp": 0.3,
        "Color_x": -0.15,
        "Color_y": 0.0,
        "Gain": -1.0,
    },
}

ALLOWED_PARAMETERS = {"Comp", "Color_x", "Color_y", "Gain"}


def voicemeeter_settings_for_preset(preset):
    settings = {
        "strip_index": DEFAULT_VOICEMEETER_STRIP["strip_index"],
        "parameters": dict(DEFAULT_VOICEMEETER_STRIP["parameters"]),
    }
    override = preset.get("voicemeeter") if isinstance(preset, dict) else None
    if not isinstance(override, dict):
        return settings

    strip_index = override.get("strip_index", settings["strip_index"])
    if isinstance(strip_index, int) and 0 <= strip_index <= 7:
        settings["strip_index"] = strip_index

    parameters = override.get("parameters", {})
    if isinstance(parameters, dict):
        for name, value in parameters.items():
            if name in ALLOWED_PARAMETERS and isinstance(value, (int, float)):
                settings["parameters"][name] = float(value)
    return settings


def apply_voicemeeter_preset(preset, enabled=False):
    if not enabled:
        return None
    if sys.platform != "win32":
        return None

    dll_path = os.path.join(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        "VB",
        "Voicemeeter",
        "VoicemeeterRemote64.dll",
    )
    if not os.path.isfile(dll_path):
        raise OSError("VoicemeeterRemote64.dll が見つかりません")

    remote = ctypes.WinDLL(dll_path)
    remote.VBVMR_Login.restype = ctypes.c_long
    remote.VBVMR_Logout.restype = ctypes.c_long
    remote.VBVMR_IsParametersDirty.restype = ctypes.c_long
    remote.VBVMR_SetParameterFloat.argtypes = [ctypes.c_char_p, ctypes.c_float]
    remote.VBVMR_SetParameterFloat.restype = ctypes.c_long
    remote.VBVMR_GetParameterFloat.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_float),
    ]
    remote.VBVMR_GetParameterFloat.restype = ctypes.c_long

    login_result = remote.VBVMR_Login()
    if login_result < 0:
        raise OSError("Voicemeeter Remote APIへ接続できません: %s" % login_result)

    settings = voicemeeter_settings_for_preset(preset)
    applied = {}
    try:
        time.sleep(0.2)
        remote.VBVMR_IsParametersDirty()
        strip_index = settings["strip_index"]
        for name, value in settings["parameters"].items():
            parameter = "Strip[%d].%s" % (strip_index, name)
            result = remote.VBVMR_SetParameterFloat(
                parameter.encode("ascii"), ctypes.c_float(value)
            )
            if result != 0:
                raise OSError("%s の設定に失敗しました: %s" % (parameter, result))

        time.sleep(0.2)
        remote.VBVMR_IsParametersDirty()
        for name, expected in settings["parameters"].items():
            parameter = "Strip[%d].%s" % (settings["strip_index"], name)
            actual = ctypes.c_float()
            result = remote.VBVMR_GetParameterFloat(
                parameter.encode("ascii"), ctypes.byref(actual)
            )
            if result != 0 or abs(actual.value - expected) > 0.05:
                raise OSError("%s の反映確認に失敗しました" % parameter)
            applied[parameter] = actual.value
        return applied
    finally:
        remote.VBVMR_Logout()
