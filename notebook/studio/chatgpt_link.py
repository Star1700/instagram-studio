"""Build the deliberate ChatGPT Image handoff URL without automating ChatGPT."""
from urllib.parse import quote

BASE = "https://chatgpt.com/?hints=image"


def image_url(prompt: str) -> str:
    encoded = quote(prompt.strip(), safe="")
    return BASE if len(encoded) > 1500 else BASE + "&q=" + encoded
