"""Preset portrait/thumbnail rendering with a bounded image cache."""
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageColor
from tools.yozakura_theme import YOZAKURA, PRESET_IMAGE_SIZE, PRESET_THUMBNAIL_SIZE
from tools.runtime_support import cache_artwork


def gallery_font(size):
    """Use the UI font, with Japanese-capable Windows fallbacks."""
    font_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    for name in ("NotoSansJP-VF.ttf", "meiryo.ttc", "YuGothM.ttc"):
        try:
            font = ImageFont.truetype(os.path.join(font_dir, name), size)
            if name == "NotoSansJP-VF.ttf":
                # This font defaults to weight 100, unlike Tk's regular face.
                font.set_variation_by_axes([500])
            return font
        except OSError:
            continue
    return ImageFont.load_default()


@cache_artwork
def preset_image_preview_data(image_path="", model_name="", size=None):
    return render_preset_image_preview(image_path, model_name, size)


def render_preset_image_preview(image_path="", model_name="", size=None, source_image=None):
    """Render a rounded preview without distorting its aspect ratio."""
    width, height = size or PRESET_IMAGE_SIZE
    width, height = int(width), int(height)
    corner_radius = max(20, min(28, width // 9))
    canvas = Image.new("RGBA", (width, height), YOZAKURA["card"])
    resolved_path = str(image_path or "").strip().strip('"')
    try:
        if resolved_path and not os.path.isabs(resolved_path):
            resolved_path = os.path.join(os.getcwd(), resolved_path)
        if source_image is None:
            if not resolved_path or not os.path.isfile(resolved_path):
                raise FileNotFoundError(resolved_path)
            with Image.open(resolved_path) as opened:
                source = opened.convert("RGBA")
        else:
            source = source_image.convert("RGBA")
        fitted = ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS,
                              centering=(0.5, 0.5))
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, width - 1, height - 1), radius=corner_radius, fill=255
        )
        canvas.paste(fitted, (0, 0), mask)
    except (OSError, ValueError, FileNotFoundError):
        draw = ImageDraw.Draw(canvas)
        top = ImageColor.getrgb(YOZAKURA["art_top"])
        bottom = ImageColor.getrgb(YOZAKURA["art_bottom"])
        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = tuple(int(a + (b-a)*ratio) for a, b in zip(top, bottom)) + (255,)
            draw.line((0, y, width, y), fill=color)
        draw.ellipse(
            (width * 0.48, -20, width * 0.88, height * 0.25),
            fill=ImageColor.getrgb(YOZAKURA["pink"]) + (34,),
        )
        draw.ellipse(
            (-44, height * 0.53, width * 0.31, height * 0.88),
            fill=ImageColor.getrgb(YOZAKURA["purple"]) + (25,),
        )
        try:
            placeholder_font = ImageFont.truetype(
                os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "YuGothM.ttc"),
                12,
            )
        except (OSError, ValueError):
            placeholder_font = ImageFont.load_default()
        draw.text(
            (16, height // 2 - 16),
            "モデル画像",
            fill=YOZAKURA["pink_light"],
            font=placeholder_font,
        )
        draw.text(
            (16, height // 2 + 9),
            model_name or "画像未設定",
            fill=YOZAKURA["muted"],
            font=placeholder_font,
        )
    # Clip both real images and the generated placeholder. Previously only
    # real images were masked, which left square placeholder corners under
    # the rounded outline and made them look diagonally cut off.
    scale = 4
    mask_large = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(mask_large).rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=corner_radius * scale,
        fill=255,
    )
    rounded_mask = mask_large.resize((width, height), Image.Resampling.LANCZOS)
    rounded_canvas = Image.new("RGBA", (width, height), YOZAKURA["card"])
    rounded_canvas.paste(canvas, (0, 0), rounded_mask)

    border_large = Image.new(
        "RGBA", (width * scale, height * scale), (0, 0, 0, 0)
    )
    ImageDraw.Draw(border_large).rounded_rectangle(
        (4, 4, width * scale - 5, height * scale - 5),
        radius=corner_radius * scale,
        outline=YOZAKURA["border"],
        width=7,
    )
    border = border_large.resize((width, height), Image.Resampling.LANCZOS)
    canvas = Image.alpha_composite(rounded_canvas, border)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def preset_add_thumbnail_data(size=None):
    """Render an empty, rounded add tile in the current gallery theme."""
    width, height = (int(value) for value in (size or PRESET_THUMBNAIL_SIZE))
    scale = 4
    radius = max(10, min(14, width // 7))
    canvas = Image.new("RGB", (width * scale, height * scale), YOZAKURA["card"])
    ImageDraw.Draw(canvas).rounded_rectangle(
        (4, 4, width * scale - 5, height * scale - 5),
        radius=radius * scale,
        fill=YOZAKURA["card_alt"],
        outline=YOZAKURA["border"],
        width=5,
    )
    canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    font = gallery_font(12)
    label = "追加 ＋"
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    draw.text(
        ((width - (right - left)) / 2 - left,
         (height - (bottom - top)) / 2 - top),
        label, font=font, fill=YOZAKURA["pink_light"],
    )
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


@cache_artwork
def preset_thumbnail_data(
    image_path="", model_name="", active=False, size=None
):
    return render_preset_thumbnail(image_path, model_name, active, size)


def render_preset_thumbnail(image_path="", model_name="", active=False, size=None, source_image=None):
    """Render a compact gallery tile with a clear selected state."""
    width, height = size or PRESET_THUMBNAIL_SIZE
    width, height = int(width), int(height)
    corner_radius = max(10, min(14, width // 7))
    background = YOZAKURA["pink_light"] if active else YOZAKURA["card_alt"]
    canvas = Image.new("RGB", (width, height), background)
    resolved_path = str(image_path or "").strip().strip('"')
    if resolved_path and not os.path.isabs(resolved_path):
        resolved_path = os.path.join(os.getcwd(), resolved_path)

    picture_height = max(68, int(round(height * 0.74)))
    try:
        if source_image is None:
            if not resolved_path or not os.path.isfile(resolved_path):
                raise FileNotFoundError(resolved_path)
            with Image.open(resolved_path) as opened:
                source = opened.convert("RGBA")
        else:
            source = source_image.convert("RGBA")
        fitted = ImageOps.fit(source, (width-10, picture_height-6),
                              method=Image.Resampling.LANCZOS, centering=(0.5, 0.42))
        canvas.paste(fitted, (5, 5), fitted.getchannel("A"))
    except (OSError, ValueError, FileNotFoundError):
        draw = ImageDraw.Draw(canvas)
        top = ImageColor.getrgb(YOZAKURA["art_top"])
        bottom = ImageColor.getrgb(YOZAKURA["art_bottom"])
        for y in range(picture_height):
            ratio = y / max(picture_height - 1, 1)
            color = tuple(int(a + (b-a)*ratio) for a, b in zip(top, bottom))
            draw.line((5, 5 + y, width - 6, 5 + y), fill=color)
        draw.ellipse((width - 46, -8, width + 12, 50), fill=YOZAKURA["art_orb"])
        draw.ellipse((-20, 52, 38, 110), fill=YOZAKURA["art_orb_alt"])

    draw = ImageDraw.Draw(canvas)
    outline = YOZAKURA["pink_light"] if active else YOZAKURA["border"]
    # An opaque name strip stays readable even over bright portraits.
    draw.rectangle((0, height - 27, width, height), fill=background)
    name_font = gallery_font(12)
    display_name = model_name or "NO MODEL"
    if draw.textlength(display_name, font=name_font) > width - 12:
        while display_name and draw.textlength(display_name + "…", font=name_font) > width - 12:
            display_name = display_name[:-1]
        display_name += "…"
    text_box = draw.textbbox((0, 0), display_name, font=name_font)
    text_width = text_box[2] - text_box[0]
    draw.text(
        ((width - text_width) / 2 - text_box[0],
         height - 14 - (text_box[3] - text_box[1]) / 2 - text_box[1]),
        display_name,
        font=name_font,
        fill=YOZAKURA["bg"] if active else YOZAKURA["text"],
    )
    if active:
        # Text plus a check mark: selection must not rely on color alone.
        badge_font = gallery_font(11)
        badge_text = "適用中"
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        badge_width = bbox[2] - bbox[0] + 21
        draw.rounded_rectangle(
            (5, 6, 5 + badge_width, 25), radius=7,
            fill=YOZAKURA["pink_light"],
        )
        draw.line((10, 15, 13, 18, 18, 12), fill=YOZAKURA["bg"], width=2)
        draw.text((22 - bbox[0], 10 - bbox[1]), badge_text,
                  font=badge_font, fill=YOZAKURA["bg"])

    # Clip the entire tile, not just its outline. This removes the square
    # background pixels that otherwise remain visible at all four corners.
    scale = 4
    mask_large = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(mask_large).rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=corner_radius * scale,
        fill=255,
    )
    rounded_mask = mask_large.resize((width, height), Image.Resampling.LANCZOS)
    rounded_canvas = Image.new("RGBA", (width, height), YOZAKURA["card"])
    rounded_canvas.paste(canvas.convert("RGBA"), (0, 0), rounded_mask)

    border_large = Image.new(
        "RGBA", (width * scale, height * scale), (0, 0, 0, 0)
    )
    ImageDraw.Draw(border_large).rounded_rectangle(
        (4, 4, width * scale - 5, height * scale - 5),
        radius=corner_radius * scale,
        outline=outline,
        width=(14 if active else 5),
    )
    border = border_large.resize((width, height), Image.Resampling.LANCZOS)
    canvas = Image.alpha_composite(rounded_canvas, border)

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()
