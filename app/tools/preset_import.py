"""Copy a model/Index pair into the portable library without replacing files."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from configs.model_presets import load_model_preset, save_model_preset


def classify_dropped_files(paths):
    """Validate one preset's drop without opening models or changing files."""
    selected = {}
    for raw in paths:
        path = Path(raw).resolve()
        key = {".pth": "model", ".index": "index"}.get(path.suffix.lower())
        if key is None or not path.is_file() or not path.stat().st_size:
            raise ValueError("空でない .pth / .index ファイルをドロップしてください。")
        if key in selected and selected[key] != str(path):
            raise ValueError("一度に追加できるのは、PTHとIndexそれぞれ1つです。")
        selected[key] = str(path)
    if not selected:
        raise ValueError(".pth / .index ファイルをドロップしてください。")
    return selected


def digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.digest()


def import_preset(app_root, model_path, index_path=""):
    root = Path(app_root).resolve()
    sources = [Path(str(model_path).strip().strip('"')).resolve()]
    if index_path:
        sources.append(Path(str(index_path).strip().strip('"')).resolve())
    for path, extension in zip(sources, (".pth", ".index")):
        if path.suffix.lower() != extension or not path.is_file() or not path.stat().st_size:
            raise ValueError("有効な%sファイルを選んでください。" % extension)
    hashes = [digest(p) for p in sources]
    number = 1
    while True:
        name = sources[0].stem + ("" if number == 1 else "_%d" % number)
        targets = [root / "assets/weights" / (name + ".pth")]
        if len(sources) == 2:
            targets.append(root / "assets/indices" / (name + ".index"))
        if all(not p.exists() or (p.is_file() and digest(p) == h)
               for p, h in zip(targets, hashes)):
            break
        number += 1
    # Stage complete copies first. Never replace an existing model or Index.
    staging_root = root / "TEMP/imports"
    staging_root.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix="preset_", dir=str(staging_root)))
    for source, target, expected in zip(sources, targets, hashes):
        if target.exists():
            continue
        temporary = staged / target.name
        shutil.copyfile(source, temporary)
        if digest(temporary) != expected:
            raise OSError("コピー検証に失敗しました。空き容量をご確認ください。")
        target.parent.mkdir(parents=True, exist_ok=True)
    for target in targets:
        temporary = staged / target.name
        if temporary.exists():
            # Windows rename fails if the destination was concurrently created.
            os.rename(temporary, target)
    staged.rmdir()  # Empty staging directory only.
    from configs.preset_library import allow_reimport
    allow_reimport(str(root), str(targets[0]))
    previous = load_model_preset(str(targets[0]), str(root))
    settings = previous or {"pitch": 0, "formant": 0.0, "index_rate": 0.0,
                            "rms_mix_rate": 0.9, "f0method": "rmvpe", "image_path": ""}
    settings["pth_path"] = str(targets[0])
    if len(targets) == 2:
        settings["index_path"] = str(targets[1])
    save_model_preset(settings, str(root))
    return str(targets[0])
