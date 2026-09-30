import io
import json

import pytest
from PIL import Image

from studio.server_api import SERVER_ERROR, UploadResult
from studio.store import Store
from studio.web import Handler, StudioApp, local_vienna_to_utc


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (900, 900), (50, 90, 75)).save(buffer, "JPEG")
    return buffer.getvalue()


class RecordingServer:
    def __init__(self, fail=False):
        self.fail = fail
        self.uploads = []
        self.posts = []

    def list_posts(self):
        return list(self.posts)

    def pull_token(self):
        return None

    def upload(self, image, caption, alt_text, publish_at, request_id=None):
        if self.fail:
            raise RuntimeError(SERVER_ERROR)
        self.uploads.append((image, caption, alt_text, publish_at))
        post_id = "a" * 32
        self.posts = [{"id": post_id, "status": "scheduled", "caption": caption}]
        return UploadResult(post_id, "scheduled", f"https://example.test/ig-out/{post_id}.jpg")


def _ready_app(tmp_path, server):
    store = Store(tmp_path)
    draft = store.create_draft("ruhiger Start")
    store.update_draft(draft["id"], headline="Neu beginnen", caption="Langsam starten.",
                       hashtags="#ruhe #training", alt_text="Grüne Fläche")
    store.save_original_image(draft["id"], _jpeg())
    app = Handler(StudioApp(store, {"server_base_url": "https://example.test", "upload_password": "x"},
                            server_api=server))
    return store, draft["id"], app


def test_vienna_morning_is_utc():
    assert local_vienna_to_utc("2026-01-15T07:00") == "2026-01-15T06:00:00Z"


def test_summer_time():
    assert local_vienna_to_utc("2026-07-15T07:00") == "2026-07-15T05:00:00Z"


def test_nonexistent_dst_time_is_rejected():
    with pytest.raises(ValueError, match="existiert"):
        local_vienna_to_utc("2026-03-29T02:30")


def test_ambiguous_dst_time_is_rejected():
    with pytest.raises(ValueError, match="zweimal"):
        local_vienna_to_utc("2026-10-25T02:30")


def test_schedule_uploads_stamped_preview_and_records_server_id(tmp_path):
    server = RecordingServer()
    store, draft_id, app = _ready_app(tmp_path, server)
    status, body, _ = app.handle("POST", f"/api/drafts/{draft_id}/send",
                                 b'{"when":"schedule","local_time":"2099-07-15T07:00"}')
    payload = json.loads(body)
    assert status == 200
    assert payload["post"]["status_label"] == "Geplant"
    image, caption, alt_text, publish_at = server.uploads[0]
    assert Image.open(io.BytesIO(image)).size == (1080, 1350)
    assert image == store.preview(draft_id)
    assert caption == "Langsam starten.\n\n#ruhe #training"
    assert alt_text == "Grüne Fläche"
    assert publish_at == "2099-07-15T05:00:00Z"
    saved = store.load_draft(draft_id)
    assert saved["server_id"] == "a" * 32
    assert saved["publish_at_local"] == "2099-07-15T07:00"
    _, posts_body, _ = app.handle("GET", "/api/posts")
    posts = json.loads(posts_body)["posts"]
    assert [post["source"] for post in posts] == ["server"]


def test_upload_failure_keeps_local_draft_and_returns_502(tmp_path):
    server = RecordingServer(fail=True)
    store, draft_id, app = _ready_app(tmp_path, server)
    status, body, _ = app.handle("POST", f"/api/drafts/{draft_id}/send", b'{"when":"now"}')
    assert status == 502
    assert json.loads(body)["error"] == SERVER_ERROR
    assert store.load_draft(draft_id)["server_id"] is None
    assert store.load_draft(draft_id)["caption"] == "Langsam starten."


def test_confirmed_draft_cannot_be_uploaded_twice(tmp_path):
    server = RecordingServer()
    _, draft_id, app = _ready_app(tmp_path, server)
    first, _, _ = app.handle("POST", f"/api/drafts/{draft_id}/send", b'{"when":"now"}')
    second, body, _ = app.handle("POST", f"/api/drafts/{draft_id}/send", b'{"when":"now"}')
    assert first == 200
    assert second == 409
    assert "bereits" in json.loads(body)["error"]
    assert len(server.uploads) == 1


@pytest.mark.parametrize("fields,message", [
    ({"caption": "a" * 2201}, "2200"),
    ({"hashtags": " ".join(f"#tag{i}" for i in range(31))}, "30 Hashtags"),
    ({"headline": "An excessively long headline " * 8}, "passt nicht"),
])
def test_invalid_draft_never_reaches_server(tmp_path, fields, message):
    server = RecordingServer()
    store, draft_id, app = _ready_app(tmp_path, server)
    store.update_draft(draft_id, **fields)
    status, body, _ = app.handle("POST", f"/api/drafts/{draft_id}/send", b'{"when":"now"}')
    assert status == 422 and message in json.loads(body)["error"]
    assert not server.uploads
    assert store.original_image(draft_id) == _jpeg()


def test_past_schedule_never_reaches_server(tmp_path):
    server = RecordingServer()
    _, draft_id, app = _ready_app(tmp_path, server)
    status, body, _ = app.handle("POST", f"/api/drafts/{draft_id}/send",
                               b'{"when":"schedule","local_time":"2020-01-01T10:00"}')
    assert status == 422 and "Zukunft" in json.loads(body)["error"]
    assert not server.uploads


def test_browser_cannot_clear_duplicate_guard(tmp_path):
    server = RecordingServer()
    store, draft_id, app = _ready_app(tmp_path, server)
    app.handle("POST", f"/api/drafts/{draft_id}/send", b'{"when":"now"}')
    status, _, _ = app.handle("PATCH", f"/api/drafts/{draft_id}", b'{"server_id":null}')
    assert status == 422
    assert store.load_draft(draft_id)["server_id"] is not None


def test_local_delete_route_removes_draft_and_keeps_server_uncontacted(tmp_path):
    server = RecordingServer()
    store, draft_id, app = _ready_app(tmp_path, server)
    status, body, _ = app.handle("POST", f"/api/drafts/{draft_id}/delete")
    assert status == 200 and json.loads(body)["deleted"] is True
    assert not list(store.drafts.glob(f"{draft_id}.*"))
    assert not server.uploads
    assert json.loads(app.handle("GET", "/api/posts")[1])["posts"] == []


def test_local_delete_route_rejects_sent_draft(tmp_path):
    server = RecordingServer()
    store, draft_id, app = _ready_app(tmp_path, server)
    store.update_draft(draft_id, server_id="a" * 32)
    status, body, _ = app.handle("POST", f"/api/drafts/{draft_id}/delete")
    assert status == 422 and "Server" in json.loads(body)["error"]
    assert store.load_draft(draft_id)["server_id"] == "a" * 32


def test_retry_after_lost_response_uses_same_request_id(tmp_path):
    class LostResponse(RecordingServer):
        def __init__(self):
            super().__init__()
            self.ids = []
        def upload(self, image, caption, alt_text, publish_at, request_id=None):
            self.ids.append(request_id)
            if len(self.ids) == 1:
                raise RuntimeError(SERVER_ERROR)
            return super().upload(image, caption, alt_text, publish_at, request_id)
    server = LostResponse()
    _, draft_id, app = _ready_app(tmp_path, server)
    assert app.handle("POST", f"/api/drafts/{draft_id}/send", b'{"when":"now"}')[0] == 502
    assert app.handle("POST", f"/api/drafts/{draft_id}/send", b'{"when":"now"}')[0] == 200
    assert server.ids == [draft_id, draft_id]
