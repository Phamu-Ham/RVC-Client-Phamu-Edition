import json
import os
import re
import hashlib
from datetime import datetime


MODEL_PRESET_KEYS = (
    "index_path",
    "image_path",
    "pitch",
    "formant",
    "index_rate",
    "rms_mix_rate",
    "f0method",
)


def portable_path(path, app_root):
    """Keep files inside the app relocatable; external paths remain explicit."""
    if not path:
        return ""
    root = os.path.abspath(app_root)
    full = os.path.abspath(os.path.join(root, str(path).strip().strip('"')))
    try:
        if os.path.normcase(os.path.commonpath([root, full])) == os.path.normcase(root):
            return os.path.relpath(full, root).replace("\\", "/")
    except ValueError:
        pass
    return full


def model_name_from_path(pth_path):
    if not pth_path:
        return ""
    normalized = os.path.normpath(str(pth_path).strip().strip('"'))
    return os.path.splitext(os.path.basename(normalized))[0]


def model_identity(pth_path, app_root):
    path = str(pth_path or "").strip().strip('"')
    if not path:
        return ""
    path = os.path.normcase(os.path.abspath(os.path.join(app_root, path)))
    root = os.path.normcase(os.path.abspath(app_root))
    try:
        if os.path.commonpath([root, path]) == root:
            return "app:" + os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        pass
    return "absolute:" + path.replace("\\", "/")

def preset_path_for_model(pth_path, app_root):
    model_name = model_name_from_path(pth_path)
    if not model_name:
        return ""
    safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", model_name).strip("._")
    safe_name = safe_name or "model"
    identity = model_identity(pth_path, app_root)
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return os.path.join(app_root, "configs", "model_presets", safe_name + "--" + suffix + ".json")

def _read_preset(pth_path, app_root):
    from configs.preset_library import is_deleted
    if is_deleted(pth_path, app_root):
        return None
    target = preset_path_for_model(pth_path, app_root)
    legacy_name = re.sub(r"[^0-9A-Za-z._-]+", "_", model_name_from_path(pth_path)).strip("._")
    legacy = os.path.join(app_root, "configs", "model_presets", legacy_name + ".json")
    for path in (target, legacy):
        try:
            with open(path, encoding="utf-8") as handle:
                preset = json.load(handle)
            if not isinstance(preset, dict):
                continue
            identity = preset.get("model_identity") or model_identity(preset.get("pth_path"), app_root)
            if identity == model_identity(pth_path, app_root):
                return preset
        except (OSError, ValueError, TypeError):
            continue
    return None


def load_model_preset(pth_path, app_root):
    preset = _read_preset(pth_path, app_root)
    if preset is None:
        return None
    result = {key: preset[key] for key in MODEL_PRESET_KEYS if key in preset}
    if isinstance(preset.get("voicemeeter"), dict):
        result["voicemeeter"] = preset["voicemeeter"]
    return result


def save_model_preset(settings, app_root):
    from configs.preset_library import _locked, is_deleted
    from pathlib import Path
    with _locked(Path(app_root).absolute()):
        if is_deleted(settings.get("pth_path", ""), app_root):
            raise ValueError("削除済みプリセットです。アプリ内のゴミ箱から復元してください。")
        return _save_model_preset(settings, app_root)


def _save_model_preset(settings, app_root):
    pth_path = settings.get("pth_path", "")
    preset_path = preset_path_for_model(pth_path, app_root)
    if not preset_path:
        raise ValueError("PTHファイルを選んでください")

    preset = {
        "schema_version": 2,
        "model_identity": model_identity(pth_path, app_root),
        "model_name": model_name_from_path(pth_path),
        "pth_path": portable_path(pth_path, app_root),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    image_path = str(settings.get("image_path", "")).strip().strip('"')
    if image_path and not os.path.isfile(os.path.join(app_root, image_path)):
        raise ValueError("プリセット画像が見つかりません: " + image_path)
    previous_preset = _read_preset(pth_path, app_root) or {}
    if isinstance(previous_preset.get("voicemeeter"), dict):
        preset["voicemeeter"] = previous_preset["voicemeeter"]
    preset.update({key: settings[key] for key in MODEL_PRESET_KEYS if key in settings})
    for key in ("index_path", "image_path"):
        if key in preset:
            preset[key] = portable_path(preset[key], app_root)

    os.makedirs(os.path.dirname(preset_path), exist_ok=True)
    temp_path = preset_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as preset_file:
        json.dump(preset, preset_file, ensure_ascii=False, indent=2)
        preset_file.write("\n")
    os.replace(temp_path, preset_path)
    return preset_path


def find_index_for_model(pth_path, app_root):
    model_name = model_name_from_path(pth_path)
    if not model_name:
        return ""
    sibling = os.path.splitext(os.path.join(app_root, pth_path))[0] + ".index"
    if os.path.isfile(sibling):
        return os.path.abspath(sibling)

    portable_index = os.path.join(app_root, "assets", "indices", model_name + ".index")
    if os.path.isfile(portable_index):
        return os.path.relpath(portable_index, app_root).replace("\\", "/")

    logs_root = os.path.join(app_root, "logs")
    exact_path = os.path.join(logs_root, model_name + ".index")
    if os.path.isfile(exact_path):
        return os.path.relpath(exact_path, app_root).replace("\\", "/")

    if not os.path.isdir(logs_root):
        return ""
    candidates = []
    for root, _, filenames in os.walk(logs_root):
        for filename in filenames:
            if filename.lower().endswith(".index") and model_name.lower() in filename.lower():
                candidates.append(os.path.join(root, filename))
    if not candidates:
        return ""
    candidates.sort(key=lambda path: (len(path), path.lower()))
    return os.path.relpath(candidates[0], app_root).replace("\\", "/")
