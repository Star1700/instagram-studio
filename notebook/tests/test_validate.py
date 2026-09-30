import pytest

from studio.validate import assemble_caption, validate_image_size, validate_post


def test_appends_hashtags_once():
    assert assemble_caption("Morgen.", "#lauf") == "Morgen.\n\n#lauf"


def test_rejects_caption_and_metadata_limits():
    with pytest.raises(ValueError, match="30 Hashtags"):
        validate_post(assemble_caption("Hi", " ".join(f"#t{i}" for i in range(31))), "alt")
    with pytest.raises(ValueError, match="2200"):
        validate_post("a" * 2201, "alt")
    with pytest.raises(ValueError, match="1000"):
        validate_post("ok", "a" * 1001)
    with pytest.raises(ValueError, match="20"):
        validate_post(" ".join(f"@user{i}" for i in range(21)), "alt")


def test_image_limits_accept_feed_shapes_and_reject_story_or_oversize():
    validate_image_size(1080, 1350, 500_000)
    validate_image_size(1080, 1080, 500_000)
    with pytest.raises(ValueError, match="Seitenverhältnis"):
        validate_image_size(1080, 1920, 500_000)
    with pytest.raises(ValueError, match="8 MB"):
        validate_image_size(1080, 1350, 8_000_001)
