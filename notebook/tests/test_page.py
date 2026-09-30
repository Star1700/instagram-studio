import io
import json
from pathlib import Path

from PIL import Image

from studio.store import Store
from studio.web import Handler, StudioApp


def test_page_has_the_german_controls():
    html = Path("notebook/static/index.html").read_text(encoding="utf-8")
    for label in ["Text erzeugen", "Bild in ChatGPT erstellen", "Referenzordner öffnen", "Bild hinzufügen",
                  "Logo auf diesem Beitrag verwenden", "Überschrift auf dem Bild", "Jetzt senden", "Planen", "Instagram verbinden"]:
        assert label in html


def test_failed_codex_keeps_idea_and_draft(tmp_path):
    def failing(*_args):
        raise RuntimeError("Codex konnte die Caption nicht erzeugen. Deine Idee und der Entwurf sind noch da.")

    class OfflineServer:
        def list_posts(self): return []
        def pull_token(self): return None

    app = Handler(StudioApp(Store(tmp_path), {"server_base_url": "https://example.test", "upload_password": "x"},
                            text_generator=failing, server_api=OfflineServer()))
    status, body, _ = app.handle("POST", "/api/drafts", json.dumps({"idea": "heute Beine"}).encode())
    draft = json.loads(body)["draft"]
    status, body, _ = app.handle("POST", f"/api/drafts/{draft['id']}/text", b'{"part":null}')
    assert status == 422
    assert Store(tmp_path).load_draft(draft["id"])["idea"] == "heute Beine"


def test_image_is_stamped_locally(tmp_path):
    class OfflineServer:
        def list_posts(self): return []
        def pull_token(self): return None

    app = Handler(StudioApp(Store(tmp_path), {"server_base_url": "https://example.test", "upload_password": "x"},
                            server_api=OfflineServer()))
    _, body, _ = app.handle("POST", "/api/drafts", b'{"idea":"bild"}')
    draft_id = json.loads(body)["draft"]["id"]
    source = io.BytesIO(); Image.new("RGB", (1080, 1350), (20, 40, 60)).save(source, "JPEG")
    boundary = "test-boundary"
    upload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"x.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode()
              + source.getvalue() + f"\r\n--{boundary}--\r\n".encode())
    status, _, _ = app.handle("POST", f"/api/drafts/{draft_id}/image", upload,
                              {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert status == 200
    assert Store(tmp_path).has_preview(draft_id)


def test_remote_post_can_be_deleted(tmp_path):
    class RecordingServer:
        def __init__(self): self.deleted = []
        def list_posts(self): return []
        def pull_token(self): return None
        def delete_post(self, post_id): self.deleted.append(post_id)

    server = RecordingServer()
    app = Handler(StudioApp(Store(tmp_path), {"server_base_url": "https://example.test", "upload_password": "x"},
                            server_api=server))
    post_id = "a" * 32
    status, _, _ = app.handle("POST", f"/api/posts/{post_id}/delete")
    assert status == 200
    assert server.deleted == [post_id]
