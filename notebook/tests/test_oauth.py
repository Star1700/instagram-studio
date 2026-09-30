from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.oauth import authorize_url, exchange_code, strip_code


def test_authorize_url_requests_only_the_two_scopes():
    url = authorize_url("123", "https://example.test/callback", "abc")
    assert url.startswith("https://www.instagram.com/oauth/authorize?")
    assert "instagram_business_basic" in url
    assert "instagram_business_content_publish" in url
    assert "manage_messages" not in url
    assert "state=abc" in url


def test_strip_code_removes_the_hash_suffix():
    assert strip_code("ABCDEF#_") == "ABCDEF"


def test_exchange_code_uses_local_secret_and_returns_long_token():
    calls = []

    def fake_http(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("oauth/access_token"):
            return {"access_token": "short-token-1234567890", "user_id": 123}
        return {"access_token": "long-token-12345678901", "expires_in": 5184000}

    result = exchange_code("app", "secret", "https://example.test/callback", "code#_", fake_http)
    assert result == {
        "access_token": "long-token-12345678901",
        "user_id": "123",
        "expires_in": 5184000,
    }
    assert calls[0][1]["form"]["client_secret"] == "secret"
    assert calls[0][1]["form"]["code"] == "code"
    assert calls[1][1]["query"]["access_token"] == "short-token-1234567890"
