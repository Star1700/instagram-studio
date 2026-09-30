"""Instagram feed validation shared by the local page and upload client."""
import re

HASHTAG = re.compile(r"(?:^|\s)#\w+", re.UNICODE)
MENTION = re.compile(r"(?:^|\s)@\w+", re.UNICODE)


def assemble_caption(caption: str, hashtags: str) -> str:
    caption = caption.strip()
    hashtags = hashtags.strip()
    if not hashtags:
        return caption
    return f"{caption}\n\n{hashtags}" if caption else hashtags


def validate_post(caption: str, alt_text: str) -> None:
    if len(caption) > 2200:
        raise ValueError("Die Caption darf höchstens 2200 Zeichen haben.")
    if len(HASHTAG.findall(caption)) > 30:
        raise ValueError("Höchstens 30 Hashtags.")
    if len(MENTION.findall(caption)) > 20:
        raise ValueError("Höchstens 20 Erwähnungen.")
    if len(alt_text) > 1000:
        raise ValueError("Der Alternativtext darf höchstens 1000 Zeichen haben.")


def validate_image_size(width: int, height: int, byte_length: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("Das Bild hat keine gültige Größe.")
    if byte_length > 8_000_000:
        raise ValueError("Das Bild darf höchstens 8 MB groß sein.")
    ratio = width / height
    if ratio < 0.8 or ratio > 1.91:
        raise ValueError("Das Seitenverhältnis muss zwischen 4:5 und 1,91:1 liegen.")
