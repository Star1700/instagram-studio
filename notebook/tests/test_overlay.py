import io

import pytest
from PIL import Image

from studio.overlay import stamp


def _jpeg(width, height, color):
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="JPEG")
    return output.getvalue()


def _logo():
    output = io.BytesIO()
    Image.new("RGBA", (140, 80), (220, 20, 20, 255)).save(output, format="PNG")
    return output.getvalue()


def test_portrait_output_is_jpeg_1080x1350():
    result = stamp(_jpeg(800, 1000, (10, 20, 30)), "Morgen", None, "portrait")
    image = Image.open(io.BytesIO(result))
    assert image.format == "JPEG"
    assert image.size == (1080, 1350)


def test_umlaut_square_and_overflow():
    result = stamp(_jpeg(1000, 1000, (1, 2, 3)), "Größe fürs Training", None, "square")
    assert Image.open(io.BytesIO(result)).size == (1080, 1080)
    with pytest.raises(ValueError, match="Überschrift passt nicht"):
        stamp(_jpeg(1080, 1350, (0, 0, 0)), "Wort " * 40, None, "portrait")


@pytest.mark.parametrize("position,point", [
    ("top_left", (100, 80)),
    ("top_right", (980, 80)),
    ("bottom_left", (100, 1270)),
    ("bottom_right", (980, 1270)),
])
def test_logo_is_stamped_in_selected_corner(position, point):
    result = stamp(_jpeg(1080, 1350, (255, 255, 255)), "", _logo(), "portrait", position)
    pixel = Image.open(io.BytesIO(result)).getpixel(point)
    assert pixel[0] > 180 and pixel[1] < 60 and pixel[2] < 60


def test_logo_position_is_validated():
    with pytest.raises(ValueError, match="Logo-Position"):
        stamp(_jpeg(1080, 1350, (255, 255, 255)), "", _logo(), "portrait", "center")
