"""Authenticated notebook client for the small starseven.at Studio API."""
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import re
import secrets

SERVER_ERROR = "Der Server hat den Beitrag nicht angenommen. Dein Entwurf ist noch da."


@dataclass(frozen=True)
class UploadResult:
    id: str
    status: str
    image_url: str


def german_status(status: str | None) -> str:
    return {
        None: "Entwurf", "draft": "Entwurf", "scheduled": "Geplant",
        "container_pending": "Wird gesendet", "sent": "Veröffentlicht", "failed": "Fehlgeschlagen",
    }.get(status, "Unbekannt")


def parse_upload_response(body: dict, base_url: str = "https://www.starseven.at", media_type="image") -> UploadResult:
    post_id = body.get("id", "")
    if not isinstance(post_id, str) or not re.fullmatch(r"[a-f0-9]{32}", post_id):
        raise ValueError("Ungültige Antwort des Servers.")
    if body.get("status") not in {"scheduled", "container_pending", "sent", "failed"}:
        raise ValueError("Unbekannter Beitragsstatus.")
    suffix = ".mp4" if media_type == "video" else ("-0.jpg" if media_type == "carousel" else ".jpg")
    image_url = f"{base_url.rstrip('/')}/ig-out/{post_id}{suffix}"
    if body.get("image_url") != image_url:
        raise ValueError("Ungültige Bildadresse des Servers.")
    return UploadResult(post_id, body["status"], image_url)


class ServerApi:
    def __init__(self, base_url: str, password: str, transport=None, account_id: str = ""):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.transport = transport or self._urlopen_transport
        self.account_id = account_id

    @staticmethod
    def _urlopen_transport(request: Request) -> tuple[int, dict, bytes]:
        try:
            with urlopen(request, timeout=180) as response:
                return response.status, dict(response.headers), response.read(10_000_000)
        except HTTPError as error:
            return error.code, dict(error.headers), error.read(1_000_000)
        except (URLError, TimeoutError, OSError):
            raise RuntimeError(SERVER_ERROR) from None

    def _request(self, path: str, *, method: str = "GET", data: bytes | None = None,
                 content_type: str | None = None, request_id: str | None = None) -> tuple[int, dict, bytes]:
        headers = {"Accept": "application/json"}
        if self.password:
            headers["Authorization"] = "Bearer " + self.password
        if self.account_id:
            headers["X-Studio-Account"] = self.account_id
        if request_id:
            headers["X-Studio-Request-Id"] = request_id
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            return self.transport(request)
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError(SERVER_ERROR) from None

    @staticmethod
    def _json(body: bytes) -> dict:
        try:
            value = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RuntimeError(SERVER_ERROR) from None
        if not isinstance(value, dict):
            raise RuntimeError(SERVER_ERROR)
        return value

    def list_posts(self) -> list[dict]:
        status, _, body = self._request("/ig-api/status.php")
        if status != 200:
            raise RuntimeError(SERVER_ERROR)
        posts = self._json(body).get("posts")
        if not isinstance(posts, list) or any(not isinstance(post, dict) for post in posts):
            raise RuntimeError(SERVER_ERROR)
        return posts

    def list_accounts(self) -> list[dict]:
        status, _, body = self._request("/ig-api/accounts.php")
        if status != 200:
            raise RuntimeError("Die Konten konnten nicht vom Server geladen werden.")
        return self._json(body).get("accounts", [])

    def start_oauth(self, state: str, verifier_hash: str, key_hash: str) -> dict:
        status, _, body = self._request("/ig-api/oauth-start.php", method="POST",
                                    data=json.dumps({"state": state, "verifier_hash": verifier_hash, "key_hash": key_hash}).encode(),
                                    content_type="application/json")
        if status != 200:
            raise RuntimeError("Die zentrale Instagram-Anmeldung ist noch nicht verfügbar. Bitte wende dich an den App-Betreiber oder versuche es später erneut.")
        result = self._json(body)
        if not isinstance(result.get("url"), str) or not result["url"].startswith("https://www.instagram.com/oauth/authorize?"):
            raise RuntimeError("Instagram hat keine gültige Anmeldeseite zurückgegeben.")
        return result

    def poll_oauth(self, state: str, verifier: str) -> dict | None:
        status, _, body = self._request("/ig-api/oauth-pickup.php", method="POST",
                                       data=json.dumps({"state": state, "verifier": verifier}).encode(), content_type="application/json")
        if status == 404:
            return None
        if status != 200:
            raise RuntimeError("Instagram konnte die Verbindung nicht bestätigen. Prüfe dein Creator- oder Business-Konto und beide Freigaben. Solange Meta die Rechte nur zum Testen freigibt, brauchst du zusätzlich eine angenommene Tester-Einladung.")
        return self._json(body)

    def push_token(self, access_token: str, user_id: str, expires_in: int) -> None:
        payload = json.dumps({"access_token": access_token, "user_id": user_id,
                              "expires_in": expires_in}).encode()
        status, _, body = self._request("/ig-api/token.php", method="POST", data=payload,
                                        content_type="application/json")
        if status != 204 or body != b"":
            raise RuntimeError(SERVER_ERROR)

    def pull_token(self) -> dict | None:
        status, _, body = self._request("/ig-api/token.php")
        if status == 404:
            return None
        if status != 200:
            raise RuntimeError(SERVER_ERROR)
        token = self._json(body)
        if (not isinstance(token.get("access_token"), str)
                or not str(token.get("user_id", "")).isdigit()
                or not isinstance(token.get("expires_in"), int)):
            raise RuntimeError(SERVER_ERROR)
        return token

    def upload(self, image: bytes, caption: str, alt_text: str, publish_at: str,
               request_id: str | None = None) -> UploadResult:
        boundary = "studio-" + secrets.token_hex(16)
        pieces: list[bytes] = []
        for name, value in {"caption": caption, "alt_text": alt_text, "publish_at": publish_at}.items():
            pieces.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"), b"\r\n",
            ])
        pieces.extend([
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="image"; filename="studio.jpg"\r\n',
            b"Content-Type: image/jpeg\r\n\r\n", image, b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        status, _, body = self._request(
            "/ig-api/upload.php", method="POST", data=b"".join(pieces),
            content_type=f"multipart/form-data; boundary={boundary}",
            request_id=request_id,
        )
        if status != 201:
            raise RuntimeError(SERVER_ERROR)
        try:
            return parse_upload_response(self._json(body), self.base_url)
        except ValueError:
            raise RuntimeError(SERVER_ERROR) from None

    def delete_post(self, post_id: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", post_id):
            raise RuntimeError(SERVER_ERROR)
        payload = json.dumps({"id": post_id}).encode("utf-8")
        status, _, body = self._request("/ig-api/delete.php", method="POST", data=payload,
                                        content_type="application/json")
        if status != 204 or body != b"":
            raise RuntimeError(SERVER_ERROR)

    def upload_media(self, media_type, media, caption, publish_at, request_id=None):
        if media_type not in {"video", "carousel"}:
            raise ValueError("Ungültige Beitragsart.")
        boundary = "studio-" + secrets.token_hex(16)
        pieces = []
        fields = {"media_type": media_type, "caption": caption, "publish_at": publish_at,
                  "alt_texts": json.dumps([alt for _, alt in media], ensure_ascii=False)}
        for name, value in fields.items():
            pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
        extension, mime = ("mp4", "video/mp4") if media_type == "video" else ("jpg", "image/jpeg")
        for index, (data, _) in enumerate(media):
            pieces.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="media_{index}"; filename="studio.{extension}"\r\nContent-Type: {mime}\r\n\r\n'.encode(), data, b"\r\n"])
        pieces.append(f"--{boundary}--\r\n".encode())
        status, _, body = self._request("/ig-api/media-upload.php", method="POST", data=b"".join(pieces),
                                       content_type=f"multipart/form-data; boundary={boundary}", request_id=request_id)
        if status != 201:
            raise RuntimeError(SERVER_ERROR)
        try:
            return parse_upload_response(self._json(body), self.base_url, media_type)
        except ValueError:
            raise RuntimeError(SERVER_ERROR) from None
