"""Portable first-run defaults and independent integration preferences."""
import json
import os
import math
from pathlib import Path

DEFAULT_SETTINGS = {
    "pth_path": "", "index_path": "", "sg_hostapi": "", "sg_input_device": "",
    "sg_output_device": "", "sg_wasapi_exclusive": False, "sr_type": "sr_model",
    "threhold": -60.0, "pitch": 0, "formant": 0.0, "index_rate": 0.0,
    "rms_mix_rate": 0.9, "block_time": 0.6, "crossfade_length": 0.15,
    "extra_time": 2.5, "n_cpu": 4, "f0method": "rmvpe", "use_jit": False,
    "use_pv": False, "I_noise_reduce": False, "O_noise_reduce": False,
}

def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)

def load_runtime_settings(app_root):
    data = dict(DEFAULT_SETTINGS)
    # Never seed a new installation from somebody else's saved device/model names.
    saved = read_json(Path(app_root) / "configs/inuse/config.json")
    for key, default in DEFAULT_SETTINGS.items():
        value = saved.get(key, default)
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else:
            valid = isinstance(value, str)
        if valid:
            data[key] = value
    if data["f0method"] not in {"pm", "harvest", "crepe", "rmvpe", "fcpe"}:
        data["f0method"] = "rmvpe"
    if data["sr_type"] not in {"sr_model", "sr_device"}:
        data["sr_type"] = "sr_model"
    return data

def choose_device(names, indices, preferred, default_index):
    if preferred in names:
        return preferred
    if default_index in indices:
        return names[indices.index(default_index)]
    return names[0] if names else ""

def integration_enabled(app_root):
    return read_json(Path(app_root) / "configs/integrations.json").get("voicemeeter_enabled") is True

def save_integration(app_root, enabled):
    write_json(Path(app_root) / "configs/integrations.json",
               {"schema_version": 1, "voicemeeter_enabled": bool(enabled)})
