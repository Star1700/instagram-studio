import json

from studio.server_api import ServerApi, german_status


def test_status_words():
    assert german_status("scheduled") == "Geplant"
    assert german_status("container_pending") == "Wird gesendet"
    assert german_status("sent") == "Veröffentlicht"
    assert german_status("failed") == "Fehlgeschlagen"
    assert german_status(None) == "Entwurf"


def test_authenticated_status_and_token_contracts():
    seen = []

    def transport(request):
        seen.append(request)
        if request.full_url.endswith("status.php"):
            return 200, {}, json.dumps({"posts": [{"id": "a", "status": "scheduled"}]}).encode()
        if request.method == "GET":
            return 200, {}, json.dumps({"access_token": "x" * 24, "user_id": "123", "expires_in": 5000}).encode()
        return 204, {}, b""

    api = ServerApi("https://example.test", "password", transport)
    assert api.list_posts()[0]["status"] == "scheduled"
    assert api.pull_token()["user_id"] == "123"
    api.push_token("x" * 24, "123", 5000)
    api.delete_post("a" * 32)
    assert all(request.headers["Authorization"] == "Bearer password" for request in seen)
    assert seen[-1].full_url.endswith("delete.php")
    assert json.loads(seen[-1].data) == {"id": "a" * 32}
