from studio.chatgpt_link import image_url


def test_short_prompt_is_in_the_query():
    url = image_url("ein ruhiges Studio")
    assert url.startswith("https://chatgpt.com/?hints=image&q=")
    assert "ruhiges" in url


def test_long_prompt_omits_the_query():
    assert image_url("x" * 1600) == "https://chatgpt.com/?hints=image"
