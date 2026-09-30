"""Apply the exact headline and an optional logo to a feed JPEG."""
from pathlib import Path
import io

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .validate import validate_image_size

OVERFLOW = "Die Überschrift passt nicht auf das Bild. Kürze sie, das Bild bleibt gleich."
FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def stamp(image_bytes: bytes, headline: str, logo_bytes: bytes | None, canvas: str,
          logo_position: str = "bottom_right") -> bytes:
    if len(image_bytes) > 8_000_000:
        raise ValueError("Das Bild darf höchstens 8 MB groß sein.")
    if canvas not in {"portrait", "square"}:
        raise ValueError("Bitte wähle Porträt oder Quadrat.")
    if logo_position not in {"bottom_right", "bottom_left", "top_right", "top_left"}:
        raise ValueError("Bitte wähle eine gültige Logo-Position.")
    size = (1080, 1350) if canvas == "portrait" else (1080, 1080)
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            if opened.width * opened.height > 40_000_000:
                raise ValueError("Bitte wähle ein Bild mit höchstens 40 Megapixeln.")
            src = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise ValueError("Bitte wähle eine gültige Bilddatei.") from None

    scale = max(size[0] / src.width, size[1] / src.height)
    resized = src.resize((round(src.width * scale), round(src.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - size[0]) // 2
    top = (resized.height - size[1]) // 2
    sheet = resized.crop((left, top, left + size[0], top + size[1]))

    clean_headline = headline.strip()
    headline_bottom = 48
    if clean_headline:
        draw = ImageDraw.Draw(sheet)
        font = _font(64)
        box = draw.textbbox((0, 0), clean_headline, font=font, stroke_width=2)
        text_width = box[2] - box[0]
        if "\n" in clean_headline or text_width > size[0] - 80:
            raise ValueError(OVERFLOW)
        x = (size[0] - text_width) // 2
        draw.text((x, 48), clean_headline, font=font, fill=(255, 255, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0))
        headline_bottom = 48 + box[3] + 24

    if logo_bytes:
        try:
            with Image.open(io.BytesIO(logo_bytes)) as opened_logo:
                logo = opened_logo.convert("RGBA")
        except (UnidentifiedImageError, OSError):
            raise ValueError("Das Logo ist keine gültige Bilddatei.") from None
        logo.thumbnail((280, 120), Image.Resampling.LANCZOS)
        x = 48 if logo_position.endswith("left") else size[0] - logo.width - 48
        y = max(48, headline_bottom) if logo_position.startswith("top") else size[1] - logo.height - 48
        sheet.paste(logo, (x, y), logo)

    output = io.BytesIO()
    sheet.save(output, format="JPEG", quality=90, optimize=True)
    data = output.getvalue()
    validate_image_size(size[0], size[1], len(data))
    return data
