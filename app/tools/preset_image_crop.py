"""Non-destructive image selection geometry and metadata-free preset PNGs."""
from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
import uuid
import warnings
from PIL import Image, ImageOps

MAX_PIXELS = 40_000_000


def load_crop_source(path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("画像が大きすぎます。4,000万画素以下の画像を選んでください。")
                # Animated formats use their first frame. Respect phone-photo orientation.
                source = ImageOps.exif_transpose(image).convert("RGBA")
                return Image.frombytes("RGBA", source.size, source.tobytes())
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("画像が大きすぎます。縮小した画像を選んでください。") from error


@dataclass
class CropState:
    width: int
    height: int
    aspect: float = 0.75
    zoom: float = 1.0
    cx: float = 0.5
    cy: float = 0.5

    def __post_init__(self):
        if self.width < 1 or self.height < 1:
            raise ValueError("画像のサイズが不正です。")
        self.set_aspect(self.aspect)

    def crop_size(self):
        width = min(self.width, self.height * self.aspect) / self.zoom
        return width, width / self.aspect

    def clamp(self):
        width, height = self.crop_size()
        self.cx = max(width / 2 / self.width, min(1 - width / 2 / self.width, self.cx))
        self.cy = max(height / 2 / self.height, min(1 - height / 2 / self.height, self.cy))

    def box(self):
        self.clamp()
        width, height = self.crop_size()
        x, y = self.cx * self.width, self.cy * self.height
        return (max(0.0, x-width/2), max(0.0, y-height/2),
                min(float(self.width), x+width/2), min(float(self.height), y+height/2))

    def set_zoom(self, value):
        if not math.isfinite(value):
            raise ValueError("拡大率が不正です。")
        self.zoom = max(1.0, min(6.0, float(value)))
        self.clamp()

    def set_aspect(self, aspect):
        if aspect not in (0.75, 1.0):
            raise ValueError("切り抜きの比率が不正です。")
        self.aspect = float(aspect)
        self.clamp()

    def reset(self):
        self.zoom, self.cx, self.cy = 1.0, 0.5, 0.5
        self.clamp()

    def pan(self, dx, dy, viewport_size):
        width, height = self.crop_size()
        self.cx -= dx * width / viewport_size[0] / self.width
        self.cy -= dy * height / viewport_size[1] / self.height
        self.clamp()

    def render(self, image, size=None):
        if size is None:
            size = (768, 1024) if self.aspect == 0.75 else (1024, 1024)
        # A reduced editing proxy has the same coordinates in normalized space.
        sx, sy = image.width / self.width, image.height / self.height
        box = tuple(value * (sx if index % 2 == 0 else sy)
                    for index, value in enumerate(self.box()))
        return image.resize(size, Image.Resampling.LANCZOS, box=box)


def save_crop(source, state, app_root):
    cropped = state.render(source).convert("RGBA")
    clean = Image.frombytes("RGBA", cropped.size, cropped.tobytes())
    buffer = BytesIO()
    clean.save(buffer, format="PNG")
    relative = Path("assets/preset_images") / ("crop_" + uuid.uuid4().hex + ".png")
    target = Path(app_root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # Unique, exclusive creation: never replace the source or an existing preset image.
    with target.open("xb") as handle:
        handle.write(buffer.getvalue())
    return relative.as_posix()
