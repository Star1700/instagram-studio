import io
import json
from pathlib import Path

import av
import pytest
from PIL import Image

from studio.codex_text import _prompt
from studio.media import prepare_video
from studio.references import References
from studio.server_api import ServerApi, UploadResult
from studio.settings import validate_profile
from studio.store import Store
from studio.web import StudioApp


def call(app, method, path, values=None):
    status, body, _ = app.handle(method, path, json.dumps(values).encode() if values else b"")
    return status, json.loads(body)


def jpeg(color=(120, 50, 30)):
    out = io.BytesIO()
    Image.new("RGB", (540, 675), color).save(out, "JPEG")
    return out.getvalue()


def multipart(app, path, data, name="file"):
    body = f'--test\r\nContent-Disposition: form-data; name="{name}"; filename="fixture"\r\n\r\n'.encode() + data + b"\r\n--test--\r\n"
    status, response, _ = app.handle("POST", path, body, {"Content-Type": "multipart/form-data; boundary=test"})
    return status, json.loads(response)


@pytest.fixture(scope="module")
def video_bytes(tmp_path_factory):
    path = tmp_path_factory.mktemp("video") / "flat.mp4"
    with av.open(str(path), "w") as output:
        stream = output.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 320, 568, "yuv420p"
        for _ in range(100):
            frame = av.VideoFrame.from_image(Image.new("RGB", (320, 568), (120, 80, 40)))
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return path.read_bytes()


def test_named_profiles_persist_across_accounts_without_copying_logos(tmp_path):
    config = {"accounts": {"111": {}, "222": {}}, "active_account_id": "111"}
    app = StudioApp(Store(tmp_path), config)
    app.store.save_profile({"logo_path": "one.bin", "handle": "one"})
    values = {"name": "Fitness", "niche": "Fitness for parents", "language": "Deutsch"}
    status, saved = call(app, "POST", "/api/writing-profiles", {"values": values})
    assert status == 200
    profile_id = saved["profile"]["id"]
    app.accounts.select("222")
    app.store.save_profile({"logo_path": "two.bin", "handle": "two"})
    assert call(app, "POST", "/api/writing-profiles/select", {"id": profile_id})[0] == 200
    profile = app.store.load_profile()
    assert profile["niche"] == values["niche"] and profile["logo_path"] == "two.bin" and profile["handle"] == "two"
    reloaded = StudioApp(Store(tmp_path), config)
    assert reloaded.writing_profiles.get(profile_id)["name"] == "Fitness"
    values.update(name="Alltag als Mama", niche="Family", language="Englisch")
    assert call(app, "POST", "/api/writing-profiles", {"values": values})[0] == 200
    app.accounts.select("111")
    assert len(app.writing_profiles.all()) == 2
    assert app.store.load_profile()["niche"] == "Fitness for parents"
    assert app.store.load_profile()["logo_path"] == "one.bin"


def test_profile_library_rejects_secrets_duplicates_and_unknown_ids(tmp_path):
    app = StudioApp(Store(tmp_path), {})
    assert call(app, "POST", "/api/writing-profiles", {"values": {"name": "Test", "access_token": "no"}})[0] == 422
    assert call(app, "POST", "/api/writing-profiles", {"values": {"name": "Test"}})[0] == 200
    assert call(app, "POST", "/api/writing-profiles", {"values": {"name": "test"}})[0] == 422
    assert call(app, "POST", "/api/writing-profiles/select", {"id": "not-existing"})[0] == 422


def test_profile_changes_reach_next_generation_and_only_allowlisted_fields(tmp_path):
    seen = {}
    def generator(profile, draft, part):
        seen.update(profile)
        return {"headline": "", "caption": "Updated", "hashtags": "", "image_prompt": "Must be ignored"}
    app = StudioApp(Store(tmp_path), {}, text_generator=generator)
    draft = app.store.create_draft("Current idea")
    app.store.update_draft(draft["id"], image_prompt="Keep this image idea")
    assert call(app, "PATCH", "/api/profile", {"niche": "Family life", "language": "Englisch"})[0] == 200
    assert call(app, "POST", f"/api/drafts/{draft['id']}/text")[0] == 200
    assert seen["niche"] == "Family life" and seen["language"] == "Englisch"
    assert app.store.load_draft(draft["id"])["image_prompt"] == "Keep this image idea"
    prompt = _prompt({**seen, "legacy_ideas": "Pausen", "reference_folder": "SECRET_PATH", "logo_path": "SECRET_LOGO"}, draft, None)
    assert "Pausen" not in prompt and "Wenn die heutige Idee davon abweicht" in prompt
    assert "SECRET_PATH" not in prompt and "SECRET_LOGO" not in prompt


def test_fresh_profile_starts_with_few_emojis(tmp_path):
    profile = Store(tmp_path).load_profile()
    assert profile["emoji"] == "Wenige Emojis"
    assert validate_profile({"emoji": ""}, profile)["emoji"] == "Wenige Emojis"
    with pytest.raises(ValueError, match="Emoji-Menge"):
        validate_profile({"emoji": "sparsam"}, profile)


def test_text_prompt_preview_uses_the_real_generator_prompt(tmp_path):
    app = StudioApp(Store(tmp_path), {})
    profile = app.store.load_profile()
    profile.update(niche="Rezepte im Alltag", emoji="Wenige Emojis", logo_path="private-logo.png")
    app.store.save_profile(profile)
    draft = app.store.create_draft("Ein einfaches Rezept zeigen")
    draft = app.store.update_draft(draft["id"], caption="Mein Entwurf", alt_text="private image")
    status, result = call(app, "POST", f"/api/drafts/{draft['id']}/text-prompt")
    assert status == 200 and result["prompt"] == _prompt(profile, draft, None)
    assert "private-logo" not in result["prompt"] and "private image" not in result["prompt"]
    assert result["codex"]["effort"] == "high"


def test_custom_image_style_is_saved_and_rejects_unknown_colors(tmp_path):
    app = StudioApp(Store(tmp_path), {})
    draft = app.store.create_draft("My idea")
    custom = {"background": "lavender", "accent": "teal", "layout": "dynamic"}
    status, result = call(app, "PATCH", f"/api/drafts/{draft['id']}", {"image_style": "custom", "image_custom": custom})
    assert status == 200 and result["draft"]["image_custom"] == custom
    assert app.store.load_draft(draft["id"])["image_custom"] == custom
    assert call(app, "PATCH", f"/api/drafts/{draft['id']}", {"image_custom": {**custom, "accent": "#000000"}})[0] == 422
    assert call(app, "POST", "/api/image-style", {"custom": custom}) == (200, {"custom": custom})
    reloaded = StudioApp(Store(tmp_path), {})
    assert call(reloaded, "GET", "/api/image-style") == (200, {"custom": custom})
    assert call(reloaded, "POST", "/api/image-style", {"custom": {**custom, "accent": "#000000"}})[0] == 422


def test_saved_logo_can_be_positioned_or_switched_off_per_post(tmp_path):
    app = StudioApp(Store(tmp_path), {})
    logo_file = io.BytesIO()
    Image.new("RGBA", (140, 80), (220, 20, 20, 255)).save(logo_file, "PNG")
    (app.store.root / "logo.bin").write_bytes(logo_file.getvalue())
    app.store.save_profile({"logo_path": "logo.bin"})

    first = app.store.create_draft("First image")
    first_id = first["id"]
    assert call(app, "PATCH", f"/api/drafts/{first_id}", {"logo_position": "top_left"})[0] == 200
    assert multipart(app, f"/api/drafts/{first_id}/image", jpeg((255, 255, 255)), "image")[0] == 200
    with Image.open(io.BytesIO(app.store.preview(first_id))) as image:
        assert image.getpixel((100, 80))[0] > 180 and image.getpixel((100, 80))[1] < 60

    assert call(app, "PATCH", f"/api/drafts/{first_id}", {"use_logo": False})[0] == 200
    assert call(app, "POST", f"/api/drafts/{first_id}/stamp", {"headline": "", "canvas": "portrait"})[0] == 200
    with Image.open(io.BytesIO(app.store.preview(first_id))) as image:
        assert image.getpixel((100, 80))[1] > 180

    second = app.store.create_draft("Another image")
    assert second["use_logo"] is True and second["logo_position"] == "bottom_right"
    assert multipart(app, f"/api/drafts/{second['id']}/image", jpeg((255, 255, 255)), "image")[0] == 200
    with Image.open(io.BytesIO(app.store.preview(second["id"]))) as image:
        assert image.getpixel((980, 1270))[0] > 180 and image.getpixel((980, 1270))[1] < 60


def test_reference_folder_is_persistent_and_shared(tmp_path):
    app = StudioApp(Store(tmp_path / "store"), {}, folder_opener=lambda path: None)
    folder = tmp_path / "my references"; folder.mkdir()
    assert call(app, "POST", "/api/references", {"action": "save", "path": str(folder)})[0] == 200
    assert References(Store(tmp_path / "store")).folder() == folder.resolve()
    opened = []; app.folder_opener = opened.append
    app._references(); app._references()
    assert opened == [folder.resolve(), folder.resolve()]
    assert call(app, "POST", "/api/references", {"action": "save", "path": "relative"})[0] == 422


def test_video_is_validated_and_remuxed_without_transcoding(video_bytes):
    ready, metadata = prepare_video(video_bytes)
    assert ready[4:8] == b"ftyp"
    assert ready.index(b"moov") < ready.index(b"mdat")
    assert metadata["width"] == 320 and metadata["fps"] == 30
    assert 3 <= metadata["duration"] < 4
    with pytest.raises(ValueError, match="MP4"):
        prepare_video(b"this is not a video")


class MediaServer:
    def __init__(self): self.uploads = []; self.fail = False
    def list_posts(self): return []
    def upload_media(self, kind, media, caption, publish_at, request_id=None):
        self.uploads.append((kind, media, caption, publish_at, request_id))
        if self.fail: raise RuntimeError("offline")
        return UploadResult("a" * 32, "scheduled", "https://example.test/video.mp4")


def test_video_upload_schedule_and_retry_keep_draft(video_bytes, tmp_path):
    server = MediaServer(); app = StudioApp(Store(tmp_path), {}, server_api=server)
    draft = app.store.create_draft("Video idea"); did = draft["id"]
    app.store.update_draft(did, media_type="video", caption="A caption", hashtags="#test", headline="Do not render this")
    assert multipart(app, f"/api/drafts/{did}/media", video_bytes)[0] == 200
    server.fail = True
    assert call(app, "POST", f"/api/drafts/{did}/send", {"when": "schedule", "local_time": "2099-08-01T10:00"})[0] == 502
    assert app.store.load_draft(did)["server_id"] is None
    server.fail = False
    assert call(app, "POST", f"/api/drafts/{did}/send", {"when": "schedule", "local_time": "2099-08-01T10:00"})[0] == 200
    kind, media, caption, when, request_id = server.uploads[-1]
    assert kind == "video" and media[0][0] == app.store.video_path(did).read_bytes()
    assert caption == "A caption\n\n#test" and when == "2099-08-01T08:00:00Z" and request_id == did
    assert call(app, "POST", f"/api/drafts/{did}/send", {"when": "now"})[0] == 409
    assert multipart(app, f"/api/drafts/{did}/media", video_bytes)[0] == 409


def test_carousel_reorders_alts_removes_and_sends_in_preview_order(tmp_path):
    server = MediaServer(); app = StudioApp(Store(tmp_path), {}, server_api=server)
    did = app.store.create_draft("Carousel")["id"]
    app.store.update_draft(did, media_type="carousel", caption="Caption", headline="Cover")
    assert call(app, "POST", f"/api/drafts/{did}/send", {"when": "now"})[0] == 422
    for color in [(230, 20, 10), (10, 230, 20), (20, 10, 230)]:
        assert multipart(app, f"/api/drafts/{did}/media", jpeg(color))[0] == 200
    items = app.store.load_draft(did)["carousel"]
    assert call(app, "POST", f"/api/drafts/{did}/media", {"id": items[1]["id"], "action": "alt", "alt_text": "Green"})[0] == 200
    assert call(app, "PATCH", f"/api/drafts/{did}", {"carousel_alts": {items[1]["id"]: "Green edited before sending"}})[0] == 200
    assert call(app, "PATCH", f"/api/drafts/{did}", {"carousel_alts": {"f" * 32: "Unknown"}})[0] == 422
    assert call(app, "POST", f"/api/drafts/{did}/media", {"id": items[1]["id"], "action": "left"})[0] == 200
    assert call(app, "POST", f"/api/drafts/{did}/media", {"id": items[2]["id"], "action": "remove"})[0] == 200
    assert not app.store.media_path(did, items[2]["id"]).exists()
    assert call(app, "POST", f"/api/drafts/{did}/send", {"when": "now"})[0] == 200
    kind, media, *_ = server.uploads[0]
    assert kind == "carousel" and len(media) == 2 and media[0][1] == "Green edited before sending"
    assert Image.open(io.BytesIO(media[0][0])).getpixel((500, 600))[1] > 200
    assert Image.open(io.BytesIO(media[1][0])).getpixel((500, 600))[0] > 200


def test_media_upload_does_not_accept_eleventh_image_or_foreign_item(tmp_path):
    app = StudioApp(Store(tmp_path), {})
    did = app.store.create_draft("Carousel")["id"]; app.store.update_draft(did, media_type="carousel")
    for _ in range(10):
        assert multipart(app, f"/api/drafts/{did}/media", jpeg())[0] == 200
    assert multipart(app, f"/api/drafts/{did}/media", jpeg())[0] == 422
    assert call(app, "POST", f"/api/drafts/{did}/media", {"id": "f" * 32, "action": "remove"})[0] == 404
    assert call(app, "POST", f"/api/drafts/{did}/delete")[0] == 200
    assert not list(app.store.drafts.glob(did + ".*"))


def test_clear_single_media_removes_image_and_unseen_alt_text(tmp_path):
    app = StudioApp(Store(tmp_path), {})
    did = app.store.create_draft("Image")['id']
    app.store.update_draft(did, alt_text="A real image", image_template="family", image_style="nature",
                           image_inputs={"scene": "Reading together on the sofa"})
    assert multipart(app, f"/api/drafts/{did}/image", jpeg(), "image")[0] == 200
    status, result = call(app, "POST", f"/api/drafts/{did}/clear-media")
    assert status == 200 and not app.store.has_preview(did)
    assert result["draft"]["alt_text"] == "" and result["draft"]["image_inputs"]["scene"] == "Reading together on the sofa"


def test_clear_carousel_and_video_removes_only_active_media(tmp_path, video_bytes):
    app = StudioApp(Store(tmp_path), {})
    did = app.store.create_draft("Media")['id']
    app.store.update_draft(did, media_type="carousel", caption="Keep this text")
    assert multipart(app, f"/api/drafts/{did}/media", jpeg())[0] == 200
    assert call(app, "POST", f"/api/drafts/{did}/clear-media")[0] == 200
    assert app.store.load_draft(did)["carousel"] == []
    assert not list(app.store.drafts.glob(did + ".*.original.jpg"))
    app.store.update_draft(did, media_type="video")
    assert multipart(app, f"/api/drafts/{did}/media", video_bytes)[0] == 200
    assert call(app, "POST", f"/api/drafts/{did}/clear-media")[0] == 200
    assert not app.store.video_path(did).exists()
    assert app.store.load_draft(did)["caption"] == "Keep this text"


def test_new_media_transport_keeps_idempotency_and_account_headers():
    seen = []
    def transport(request):
        seen.append(request)
        return 201, {}, json.dumps({"id": "a" * 32, "status": "scheduled", "image_url": "https://example.test/ig-out/" + "a" * 32 + "-0.jpg"}).encode()
    result = ServerApi("https://example.test", "secret", transport, "123").upload_media("carousel", [(jpeg(), "First"), (jpeg(), "Second")], "Caption", "2099-01-01T00:00:00Z", request_id="b" * 32)
    assert result.id == "a" * 32
    assert seen[0].get_header("X-studio-request-id") == "b" * 32
    assert seen[0].get_header("X-studio-account") == "123"
    assert b'name="media_0"' in seen[0].data and b'name="media_1"' in seen[0].data
    assert b"secret" not in seen[0].data
