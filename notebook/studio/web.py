"""Private localhost web page for preparing Instagram feed posts."""
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import io
import time
from PIL import Image
from .accounts import Accounts
from .settings import codex_settings, model_catalogue, validate_profile, runtime_health, PRESETS, TONES, PROFILE_FIELDS
from .writing_profiles import WritingProfiles
from .references import References
from .media import prepare_video
from .presence import Presence

from .chatgpt_link import image_url
from .codex_text import FIELDS as TEXT_FIELDS, generate, _prompt
from .overlay import stamp
from .server_api import ServerApi, SERVER_ERROR, german_status
from .store import Store
from .validate import assemble_caption, validate_post

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebook"
STATIC = NOTEBOOK / "static"
CONFIG_PATH = NOTEBOOK / "config.local.json"
DATA_ROOT = NOTEBOOK / "data"
MAX_BODY = 102_000_000
JSON_TYPE = "application/json; charset=utf-8"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _load_config() -> dict:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError("Die lokale Konfiguration ist ungültig.")
    return value


def _save_config(value: dict) -> None:
    temporary = CONFIG_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, CONFIG_PATH)


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _parse_json(body: bytes) -> dict:
    try:
        value = json.loads(body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError(400, "Die Anfrage ist ungültig.") from None
    if not isinstance(value, dict):
        raise ApiError(400, "Die Anfrage ist ungültig.")
    return value


def local_vienna_to_utc(value: str) -> str:
    try:
        local = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        raise ValueError("Bitte wähle ein gültiges Datum und eine Uhrzeit.") from None
    vienna = ZoneInfo("Europe/Vienna")
    first = local.replace(tzinfo=vienna, fold=0)
    second = local.replace(tzinfo=vienna, fold=1)
    first_utc = first.astimezone(timezone.utc)
    second_utc = second.astimezone(timezone.utc)
    first_valid = first_utc.astimezone(vienna).replace(tzinfo=None) == local
    second_valid = second_utc.astimezone(vienna).replace(tzinfo=None) == local
    if not first_valid and not second_valid:
        raise ValueError("Diese Uhrzeit existiert in Wien wegen der Zeitumstellung nicht.")
    if first_valid and second_valid and first.utcoffset() != second.utcoffset():
        raise ValueError("Diese Uhrzeit kommt in Wien wegen der Zeitumstellung zweimal vor. Bitte wähle eine andere Uhrzeit.")
    aware = first if first_valid else second
    utc = aware.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _multipart(body: bytes, content_type: str) -> dict[str, tuple[str, bytes]]:
    message = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + content_type.encode("ascii", "strict") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    result: dict[str, tuple[str, bytes]] = {}
    if not message.is_multipart():
        raise ApiError(400, "Bitte wähle eine Bilddatei.")
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if isinstance(name, str):
            result[name] = (part.get_filename() or "", part.get_payload(decode=True) or b"")
    return result


class StudioApp:
    draft_route = re.compile(r"\A/api/drafts/([a-f0-9]{32})(?:/(text|text-prompt|chatgpt|references|image|media|clear-media|stamp|send|delete|preview\.jpg|video\.mp4))?\Z")
    media_route = re.compile(r"\A/api/drafts/([a-f0-9]{32})/media/([a-f0-9]{32})\.jpg\Z")
    remote_post_route = re.compile(r"\A/api/posts/([a-f0-9]{32})/delete\Z")

    def __init__(self, store: Store | None = None, config: dict | None = None, text_generator=generate,
                 folder_opener=None, server_api: ServerApi | None = None):
        self.base_store = store or Store(DATA_ROOT)
        self.config = config if config is not None else _load_config()
        self.text_generator = text_generator
        self.folder_opener = folder_opener or self._open_folder
        self.injected_server = server_api
        self.accounts = Accounts(self.config, self.base_store, self._persist)
        self.writing_profiles = WritingProfiles(self.base_store)
        self.references = References(self.base_store)
        self.account_lock = threading.RLock()
        self.send_lock = threading.Lock()
        self.presence = Presence()

    @staticmethod
    def _open_folder(path: Path) -> None:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _persist(self):
        if self.base_store.root == DATA_ROOT:
            _save_config(self.config)

    @property
    def store(self):
        return self.accounts.store()

    @property
    def server(self):
        return self.injected_server or self.accounts.api()

    def sync_token(self) -> bool:
        if not self.accounts.active_id:
            return False
        token = self.server.pull_token()
        if token is None or token["user_id"] != self.accounts.active_id:
            return False
        record = self.config["accounts"][self.accounts.active_id]
        record.update(access_token=token["access_token"], expires_at=token.get("expires_at", ""))
        self._persist()
        return True

    def _logo_bytes(self, draft: dict | None = None) -> bytes | None:
        if draft is not None and draft.get("use_logo") is False:
            return None
        logo_name = self.store.load_profile().get("logo_path", "")
        if not isinstance(logo_name, str) or not logo_name:
            return None
        path = self.store.root / logo_name
        return path.read_bytes() if path.is_file() and path.parent == self.store.root else None

    def _draft_payload(self, draft: dict) -> dict:
        value = dict(draft)
        value["status_label"] = german_status(value.get("status"))
        value["preview_url"] = (f"/api/drafts/{draft['id']}/preview.jpg" if self.store.has_preview(draft["id"]) else None)
        value["carousel"] = [{**item, "preview_url": f"/api/drafts/{draft['id']}/media/{item['id']}.jpg"}
                             for item in draft.get("carousel", [])]
        value["video_url"] = f"/api/drafts/{draft['id']}/video.mp4" if self.store.video_path(draft["id"]).exists() else None
        return value

    def _stamp_carousel(self, draft):
        for index, item in enumerate(draft.get("carousel", [])):
            original = self.store.media_path(draft["id"], item["id"]).read_bytes()
            preview = stamp(original, draft.get("headline", "") if index == 0 else "",
                            self._logo_bytes(draft), draft.get("canvas", "portrait"),
                            draft.get("logo_position", "bottom_right"))
            self.store.media_path(draft["id"], item["id"], "preview").write_bytes(preview)

    def _posts(self) -> dict:
        local = [self._draft_payload(draft) for draft in self.store.list_drafts() if not draft.get("server_id")]
        warning = None
        try:
            remote = self.server.list_posts() if self.accounts.active_id or self.injected_server else []
        except RuntimeError:
            remote = []
            warning = "Der Serverstatus ist gerade nicht erreichbar. Deine lokalen Entwürfe sind weiterhin da."
        for post in remote:
            post["status_label"] = german_status(post.get("status"))
            post["source"] = "server"
        for draft in local:
            draft["source"] = "local"
        return {"posts": local + remote, "warning": warning}

    def _references(self) -> Path:
        self.references.open(self.folder_opener)
        return self.references.folder()

    def handle(self, method: str, raw_path: str, body: bytes = b"", headers: dict | None = None) -> tuple[int, bytes, str]:
        if urlsplit(raw_path).path == "/api/presence":
            return self._handle(method, raw_path, body, headers)
        with self.account_lock:
            return self._handle(method, raw_path, body, headers)

    def _handle(self, method, raw_path, body, headers):
        path = urlsplit(raw_path).path
        headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
        try:
            selected = headers.get("x-studio-local-account")
            if selected is not None and selected != self.accounts.active_id and not (path == "/api/profile" and method == "GET") and path != "/api/presence":
                raise ApiError(409, "Das Konto wurde in einem anderen Fenster gewechselt. Lade Studio neu.")
            if len(body) > MAX_BODY:
                raise ApiError(413, "Bilder dürfen höchstens 8 MB, Videos höchstens 100 MB groß sein.")
            if method == "GET" and path == "/":
                return 200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8"
            if method == "POST" and path == "/api/presence":
                values = _parse_json(body)
                self.presence.update(values.get("tab_id"), values.get("action"))
                return 204, b"", JSON_TYPE
            if method == "GET" and path in {"/app.css", "/app.js"}:
                file = STATIC / path.removeprefix("/")
                return 200, file.read_bytes(), mimetypes.guess_type(file.name)[0] + "; charset=utf-8"
            if method == "GET" and re.fullmatch(r"/templates/[a-z-]+\.png", path):
                return 200, (STATIC / path.lstrip("/")).read_bytes(), "image/png"
            if method == "GET" and path == "/api/image-templates":
                return 200, (STATIC / "image-templates.json").read_bytes(), JSON_TYPE
            if method == "GET" and path == "/api/image-style":
                return 200, _json_bytes({"custom": self.base_store.load_custom_style()}), JSON_TYPE
            if method == "POST" and path == "/api/image-style":
                custom = self.base_store.save_custom_style(_parse_json(body).get("custom"))
                return 200, _json_bytes({"custom": custom}), JSON_TYPE
            if method == "GET" and path == "/api/posts":
                return 200, _json_bytes(self._posts()), JSON_TYPE
            if method == "GET" and path == "/api/profile":
                profile = self.store.load_profile()
                return 200, _json_bytes({"profile": profile, "connected": bool(self.accounts.active_id),
                                         "codex": codex_settings(profile), **self.accounts.public(),
                                         "models": model_catalogue(), "presets": PRESETS, "tones": TONES,
                                         "writing_profiles": self.writing_profiles.all(),
                                         "reference_folder": str(self.references.folder())}), JSON_TYPE
            if method == "GET" and path == "/api/setup":
                return 200, _json_bytes(runtime_health()), JSON_TYPE
            if method == "PATCH" and path == "/api/profile":
                profile = validate_profile(_parse_json(body), self.store.load_profile())
                self.store.save_profile(profile)
                return 200, _json_bytes({"saved": True, "codex": codex_settings(profile)}), JSON_TYPE
            if method == "POST" and path == "/api/writing-profiles":
                values = _parse_json(body)
                if not isinstance(values.get("values"), dict):
                    raise ApiError(422, "Ungültiges Schreibprofil.")
                item = self.writing_profiles.save(values["values"], values.get("id"))
                profile = validate_profile(item["values"], self.store.load_profile())
                profile["writing_profile_id"] = item["id"]
                profile["setup_complete"] = True
                self.store.save_profile(profile)
                return 200, _json_bytes({"profile": item}), JSON_TYPE
            if method == "POST" and path == "/api/writing-profiles/select":
                selected_id = _parse_json(body).get("id", "")
                profile = self.store.load_profile()
                if selected_id:
                    item = self.writing_profiles.get(selected_id)
                    profile = validate_profile({key: value for key, value in item["values"].items() if key in PROFILE_FIELDS}, profile)
                profile["writing_profile_id"] = selected_id
                self.store.save_profile(profile)
                return 200, _json_bytes({"saved": True}), JSON_TYPE
            if method == "POST" and path == "/api/references":
                values = _parse_json(body)
                if values.get("action") == "choose":
                    self.references.choose()
                elif values.get("action") == "save":
                    self.references.set(values.get("path"))
                elif values.get("action") == "open":
                    self.references.open(self.folder_opener)
                else:
                    raise ApiError(422, "Ungültige Ordneraktion.")
                return 200, _json_bytes({"path": str(self.references.folder())}), JSON_TYPE
            if method == "POST" and path == "/api/accounts/select":
                self.accounts.select(_parse_json(body).get("id", ""))
                return 200, _json_bytes(self.accounts.public()), JSON_TYPE
            if method == "POST" and path == "/api/accounts/check":
                return 200, _json_bytes({"account": self.accounts.check()}), JSON_TYPE
            if method == "POST" and path == "/api/oauth/poll":
                return 200, _json_bytes(self.accounts.poll()), JSON_TYPE
            if method == "POST" and path == "/api/drafts":
                draft = self.store.create_draft(str(_parse_json(body).get("idea", "")))
                return 201, _json_bytes({"draft": self._draft_payload(draft)}), JSON_TYPE
            if method == "POST" and path == "/api/oauth/start":
                return 200, _json_bytes(self.accounts.start()), JSON_TYPE
            if method == "POST" and path == "/api/profile/logo":
                parts = _multipart(body, headers.get("content-type", ""))
                logo = parts.get("logo", ("", b""))[1]
                if not logo or len(logo) > 4_000_000:
                    raise ApiError(422, "Bitte wähle ein Logo bis 4 MB.")
                try:
                    with Image.open(io.BytesIO(logo)) as image:
                        image.verify()
                except Exception:
                    raise ApiError(422, "Bitte wähle eine gültige Bilddatei als Logo.") from None
                (self.store.root / "logo.bin").write_bytes(logo)
                profile = self.store.load_profile()
                profile["logo_path"] = "logo.bin"
                self.store.save_profile(profile)
                return 200, _json_bytes({"saved": True}), JSON_TYPE
            if method == "GET" and path == "/api/profile/logo":
                logo = self._logo_bytes()
                if logo is None:
                    raise ApiError(404, "Kein Logo gespeichert.")
                return 200, logo, "image/png"

            remote_post = self.remote_post_route.fullmatch(path)
            if remote_post:
                if method != "POST":
                    raise ApiError(404, "Seite nicht gefunden.")
                try:
                    self.server.delete_post(remote_post.group(1))
                except RuntimeError:
                    raise ApiError(502, "Der Beitrag konnte nicht gelöscht werden. Versuche es erneut.") from None
                return 200, _json_bytes({"deleted": True}), JSON_TYPE

            media_match = self.media_route.fullmatch(path)
            if method == "GET" and media_match:
                draft_id, item_id = media_match.groups()
                draft = self.store.load_draft(draft_id)
                if not any(item["id"] == item_id for item in draft.get("carousel", [])):
                    raise ApiError(404, "Bild nicht gefunden.")
                return 200, self.store.media_path(draft_id, item_id, "preview").read_bytes(), "image/jpeg"
            match = self.draft_route.fullmatch(path)
            if not match:
                raise ApiError(404, "Seite nicht gefunden.")
            draft_id, action = match.groups()
            if method == "GET" and action is None:
                return 200, _json_bytes({"draft": self._draft_payload(self.store.load_draft(draft_id))}), JSON_TYPE
            if method == "PATCH" and action is None:
                supplied = _parse_json(body)
                if set(supplied) & {"server_id", "status"}:
                    raise ApiError(422, "Der Versandstatus kann nicht bearbeitet werden.")
                draft = self.store.update_draft(draft_id, **supplied)
                return 200, _json_bytes({"draft": self._draft_payload(draft)}), JSON_TYPE
            if method == "POST" and action == "delete":
                self.store.delete_draft(draft_id)
                return 200, _json_bytes({"deleted": True}), JSON_TYPE
            if method == "GET" and action == "preview.jpg":
                return 200, self.store.preview(draft_id), "image/jpeg"
            if method == "GET" and action == "video.mp4":
                self.store.load_draft(draft_id)
                return 200, self.store.video_path(draft_id).read_bytes(), "video/mp4"
            if method != "POST":
                raise ApiError(404, "Seite nicht gefunden.")

            draft = self.store.load_draft(draft_id)
            if draft.get("server_id") and action in {"image", "media", "clear-media", "stamp", "text"}:
                raise ApiError(409, "Dieser Beitrag wurde bereits übertragen. Erstelle einen neuen Entwurf.")
            if action == "clear-media":
                kind = draft.get("media_type", "image")
                if kind == "carousel":
                    for item in draft.get("carousel", []):
                        for name in ("original", "preview"):
                            self.store.media_path(draft_id, item["id"], name).unlink(missing_ok=True)
                    draft["carousel"] = []
                elif kind == "video":
                    self.store.video_path(draft_id).unlink(missing_ok=True)
                    draft.pop("video_metadata", None)
                else:
                    for name in ("original", "preview"):
                        self.store._image_path(draft_id, name).unlink(missing_ok=True)
                    draft["alt_text"] = ""
                self.store.save_media_state(draft)
                return 200, _json_bytes({"draft": self._draft_payload(draft)}), JSON_TYPE
            if action == "media":
                if headers.get("content-type", "").startswith("multipart/form-data"):
                    parts = _multipart(body, headers.get("content-type", ""))
                    data = parts.get("file", ("", b""))[1]
                    if draft.get("media_type") == "video":
                        ready, metadata = prepare_video(data)
                        temporary = self.store.video_path(draft_id).with_suffix(".tmp")
                        temporary.write_bytes(ready)
                        os.replace(temporary, self.store.video_path(draft_id))
                        draft["video_metadata"] = metadata
                        self.store.save_media_state(draft)
                    elif draft.get("media_type") == "carousel":
                        if len(draft.get("carousel", [])) >= 10:
                            raise ApiError(422, "Ein Karussell kann höchstens zehn Bilder enthalten.")
                        preview = stamp(data, draft.get("headline", "") if not draft.get("carousel") else "",
                                        self._logo_bytes(draft), draft.get("canvas", "portrait"),
                                        draft.get("logo_position", "bottom_right"))
                        draft = self.store.add_carousel_image(draft_id, data, preview)
                    else:
                        raise ApiError(422, "Bitte wähle zuerst Karussell oder Video.")
                else:
                    values = _parse_json(body)
                    items = draft.get("carousel", [])
                    item = next((item for item in items if item["id"] == values.get("id")), None)
                    if item is None:
                        raise ApiError(404, "Bild nicht gefunden.")
                    index = items.index(item)
                    operation = values.get("action")
                    if operation == "remove":
                        items.remove(item)
                    elif operation in {"left", "right"}:
                        other = index + (-1 if operation == "left" else 1)
                        if 0 <= other < len(items):
                            items[index], items[other] = items[other], items[index]
                    elif operation == "alt":
                        alt = values.get("alt_text", "")
                        if not isinstance(alt, str) or len(alt) > 1000:
                            raise ApiError(422, "Der Alternativtext darf höchstens 1000 Zeichen haben.")
                        item["alt_text"] = alt
                    else:
                        raise ApiError(422, "Ungültige Bildaktion.")
                    self._stamp_carousel(draft)
                    self.store.save_media_state(draft)
                    if operation == "remove":
                        for kind in ("original", "preview"):
                            self.store.media_path(draft_id, item["id"], kind).unlink(missing_ok=True)
                return 200, _json_bytes({"draft": self._draft_payload(draft)}), JSON_TYPE
            if action == "text":
                part = _parse_json(body).get("part")
                values = self.text_generator(self.store.load_profile(), draft, part)
                draft = self.store.update_draft(draft_id, **{field: values[field] for field in TEXT_FIELDS})
                return 200, _json_bytes({"draft": self._draft_payload(draft)}), JSON_TYPE
            if action == "text-prompt":
                profile = self.store.load_profile()
                return 200, _json_bytes({"prompt": _prompt(profile, draft, None),
                                         "codex": codex_settings(profile)}), JSON_TYPE
            if action == "chatgpt":
                prompt = draft.get("image_prompt", "").strip()
                if not prompt:
                    raise ApiError(422, "Erzeuge oder schreibe zuerst einen Bild-Prompt.")
                return 200, _json_bytes({"url": image_url(prompt), "prompt": prompt}), JSON_TYPE
            if action == "references":
                self._references()
                return 200, _json_bytes({"opened": True}), JSON_TYPE
            if action == "image":
                parts = _multipart(body, headers.get("content-type", ""))
                image = parts.get("image", ("", b""))[1]
                if not image:
                    raise ApiError(422, "Bitte wähle eine Bilddatei.")
                preview = stamp(image, draft.get("headline", ""), self._logo_bytes(draft),
                                draft.get("canvas", "portrait"), draft.get("logo_position", "bottom_right"))
                self.store.save_original_image(draft_id, image)
                self.store.save_preview(draft_id, preview)
                return 200, _json_bytes({"preview_url": f"/api/drafts/{draft_id}/preview.jpg"}), JSON_TYPE
            if action == "stamp":
                supplied = _parse_json(body)
                headline = str(supplied.get("headline", draft.get("headline", "")))
                canvas = str(supplied.get("canvas", draft.get("canvas", "portrait")))
                if draft.get("media_type") in {"carousel", "video"}:
                    draft = self.store.update_draft(draft_id, headline=headline, canvas=canvas)
                    if draft.get("media_type") == "carousel":
                        self._stamp_carousel(draft)
                    return 200, _json_bytes({"draft": self._draft_payload(draft)}), JSON_TYPE
                preview = stamp(self.store.original_image(draft_id), headline, self._logo_bytes(draft), canvas,
                                draft.get("logo_position", "bottom_right"))
                self.store.save_preview(draft_id, preview)
                draft = self.store.update_draft(draft_id, headline=headline, canvas=canvas)
                return 200, _json_bytes({"draft": self._draft_payload(draft),
                                         "preview_url": f"/api/drafts/{draft_id}/preview.jpg"}), JSON_TYPE
            if action == "send":
                if not self.accounts.active_id and not self.injected_server:
                    raise ApiError(409, "Verbinde zuerst dein Instagram-Konto.")
                supplied = _parse_json(body)
                when = supplied.get("when")
                if when not in {"now", "schedule"}:
                    raise ApiError(422, "Bitte wähle Jetzt senden oder Planen.")
                if when == "schedule":
                    local_time = str(supplied.get("local_time", ""))
                    if not local_time:
                        raise ApiError(422, "Bitte wähle ein Datum und eine Uhrzeit.")
                    publish_at = local_vienna_to_utc(local_time)
                    if datetime.fromisoformat(publish_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                        raise ApiError(422, "Bitte wähle einen Zeitpunkt in der Zukunft.")
                else:
                    local_time = None
                    publish_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                with self.send_lock:
                    draft = self.store.load_draft(draft_id)
                    if draft.get("server_id"):
                        raise ApiError(409, "Dieser Entwurf wurde bereits an den Server übertragen.")
                    full_caption = assemble_caption(draft.get("caption", ""), draft.get("hashtags", ""))
                    validate_post(full_caption, draft.get("alt_text", "") if draft.get("media_type", "image") == "image" else "")
                    media_type = draft.get("media_type", "image")
                    if media_type == "video":
                        if not self.store.video_path(draft_id).exists():
                            raise ApiError(422, "Bitte wähle zuerst ein Video.")
                        media = [(self.store.video_path(draft_id).read_bytes(), "")]
                    elif media_type == "carousel":
                        if not 2 <= len(draft.get("carousel", [])) <= 10:
                            raise ApiError(422, "Wähle zwei bis zehn Bilder für dein Karussell.")
                        self._stamp_carousel(draft)
                        media = [(self.store.media_path(draft_id, item["id"], "preview").read_bytes(), item.get("alt_text", ""))
                                 for item in draft["carousel"]]
                    else:
                        try:
                            preview = stamp(self.store.original_image(draft_id), draft.get("headline", ""),
                                            self._logo_bytes(draft), draft.get("canvas", "portrait"),
                                            draft.get("logo_position", "bottom_right"))
                        except FileNotFoundError:
                            raise ApiError(422, "Bitte wähle zuerst ein Bild.") from None
                        self.store.save_preview(draft_id, preview)
                    try:
                        if media_type == "image":
                            result = self.server.upload(preview, full_caption, draft.get("alt_text", ""), publish_at, request_id=draft_id)
                        else:
                            result = self.server.upload_media(media_type, media, full_caption, publish_at, request_id=draft_id)
                    except RuntimeError:
                        raise ApiError(502, SERVER_ERROR) from None
                    draft = self.store.update_draft(
                        draft_id, server_id=result.id, status=result.status, publish_at_local=local_time
                    )
                return 200, _json_bytes({"draft": self._draft_payload(draft), "post": {
                    "id": result.id, "status": result.status, "status_label": german_status(result.status),
                    "image_url": result.image_url,
                }}), JSON_TYPE
            raise ApiError(404, "Seite nicht gefunden.")
        except ApiError as error:
            return error.status, _json_bytes({"error": str(error)}), JSON_TYPE
        except KeyError:
            return 404, _json_bytes({"error": "Entwurf nicht gefunden."}), JSON_TYPE
        except (ValueError, RuntimeError, FileNotFoundError) as error:
            return 422, _json_bytes({"error": str(error)}), JSON_TYPE
        except Exception:
            return 500, _json_bytes({"error": "Die Anfrage konnte nicht verarbeitet werden."}), JSON_TYPE


class Handler:
    """Small testable facade named by the implementation plan."""
    def __init__(self, app: StudioApp):
        self.app = app

    def handle(self, method: str, path: str, body: bytes = b"", headers: dict | None = None):
        return self.app.handle(method, path, body, headers)


class RequestHandler(BaseHTTPRequestHandler):
    application: Handler
    presence_ping_interval = 2.0

    def _stream_presence(self, body: bytes) -> None:
        try:
            tab_id = _parse_json(body).get("tab_id")
            self.application.app.presence.update(tab_id, "touch")
        except (ApiError, ValueError, TypeError):
            payload = _json_bytes({"error": "Ungültiger Studio-Tab."})
            self.send_response(422)
            self.send_header("Content-Type", JSON_TYPE)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            while True:
                self.wfile.write(b": studio\n\n")
                self.wfile.flush()
                self.application.app.presence.update(tab_id, "touch")
                time.sleep(self.presence_ping_interval)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.application.app.presence.update(tab_id, "leave")

    def _dispatch(self) -> None:
        expected = f"127.0.0.1:{self.server.server_port}"
        origin = self.headers.get("Origin")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = MAX_BODY + 1
        if (self.headers.get("Host") != expected or (origin and origin != "http://" + expected)
                or (self.command != "GET" and self.headers.get("X-Studio-Request") != "1")):
            result = (403, _json_bytes({"error": "Bitte öffne Studio direkt auf diesem PC."}), JSON_TYPE)
        elif length < 0 or length > MAX_BODY:
            body = b""
            result = (413, _json_bytes({"error": "Bilder dürfen höchstens 8 MB, Videos höchstens 100 MB groß sein."}), JSON_TYPE)
        else:
            body = self.rfile.read(length) if length else b""
            if self.command == "POST" and urlsplit(self.path).path == "/api/presence/stream":
                self._stream_presence(body)
                return
            result = self.application.handle(self.command, self.path, body, dict(self.headers.items()))
        status, payload, content_type = result
        range_header = None
        if status == 200 and content_type == "video/mp4" and self.headers.get("Range"):
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers["Range"])
            length = len(payload)
            if match and (match[1] or match[2]):
                start = int(match[1]) if match[1] else max(0, length - int(match[2]))
                end = min(int(match[2]), length - 1) if match[1] and match[2] else length - 1
                if start < length and end >= start:
                    payload, status = payload[start:end + 1], 206
                    range_header = f"bytes {start}-{end}/{length}"
                else:
                    payload, status, range_header = b"", 416, f"bytes */{length}"
        self.send_response(status)
        if content_type == "video/mp4":
            self.send_header("Accept-Ranges", "bytes")
        if range_header:
            self.send_header("Content-Range", range_header)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PATCH = _dispatch

    def log_message(self, *_args) -> None:
        pass


def serve_until_closed(server: ThreadingHTTPServer, presence: Presence, check_interval=1.0) -> None:
    def monitor():
        while not presence.should_stop():
            time.sleep(check_interval)
        server.shutdown()

    watcher = threading.Thread(target=monitor, name="studio-presence", daemon=True)
    watcher.start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


def main() -> None:
    config = _load_config()
    app = StudioApp(config=config)
    try:
        app.sync_token()
    except RuntimeError:
        pass
    RequestHandler.application = Handler(app)
    port = int(config.get("listen_port", 8765))
    if not 1024 <= port <= 65535:
        raise RuntimeError("Der lokale Port ist ungültig.")
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    print(f"Instagram Studio läuft auf http://127.0.0.1:{port}/", flush=True)
    serve_until_closed(server, app.presence)


if __name__ == "__main__":
    main()
