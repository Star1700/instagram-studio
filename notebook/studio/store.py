"""Private local profile, draft, and image storage."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import secrets

DRAFT_ID = re.compile(r"\A[a-f0-9]{32}\Z")
DRAFT_FIELDS = {
    "idea", "headline", "caption", "hashtags", "alt_text", "image_prompt", "canvas",
    "publish_at_local", "server_id", "status", "use_logo", "logo_position", "media_type", "image_template", "image_style", "image_custom", "image_inputs", "carousel_alts",
}
IMAGE_STYLES = {"none", "warm", "nature", "bold", "pastel", "evening", "custom"}
LOGO_POSITIONS = {"bottom_right", "bottom_left", "top_right", "top_left"}
IMAGE_CUSTOM_CHOICES = {
    "background": {"ivory", "sand", "blush", "mint", "midnight", "charcoal", "peach", "lavender", "powder", "forest", "plum"},
    "accent": {"terracotta", "coral", "sage", "sun", "lilac", "sky", "berry", "teal", "cobalt", "peach", "bronze"},
    "layout": {"editorial", "graphic", "playful", "dynamic"},
}
DEFAULT_IMAGE_CUSTOM = {"background": "ivory", "accent": "terracotta", "layout": "editorial"}


def validate_image_custom(custom: dict) -> dict:
    if (not isinstance(custom, dict) or set(custom) != set(IMAGE_CUSTOM_CHOICES)
            or any(not isinstance(value, str) or value not in IMAGE_CUSTOM_CHOICES[key]
                   for key, value in custom.items())):
        raise ValueError("Ungültige eigene Farbwelt.")
    return dict(custom)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.drafts = self.root / "drafts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.drafts.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path) -> dict:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Ungültige lokale Daten.")
        return value

    @staticmethod
    def _require_id(draft_id: str) -> str:
        if not DRAFT_ID.fullmatch(draft_id):
            raise KeyError("Entwurf nicht gefunden.")
        return draft_id

    def load_profile(self) -> dict:
        path = self.root / "profile.json"
        if not path.exists():
            seed = Path(__file__).with_name("profile_seed.json")
            self._write_json(path, self._read_json(seed))
        return self._read_json(path)

    def save_profile(self, profile: dict) -> None:
        if not isinstance(profile, dict):
            raise ValueError("Ungültiges Profil.")
        self._write_json(self.root / "profile.json", profile)

    def load_custom_style(self) -> dict:
        path = self.root / "image-style.json"
        return validate_image_custom(self._read_json(path)) if path.exists() else dict(DEFAULT_IMAGE_CUSTOM)

    def save_custom_style(self, custom: dict) -> dict:
        saved = validate_image_custom(custom)
        self._write_json(self.root / "image-style.json", saved)
        return saved

    def create_draft(self, idea: str) -> dict:
        if not isinstance(idea, str):
            raise ValueError("Bitte gib eine Idee ein.")
        draft_id = secrets.token_hex(16)
        draft = {
            "id": draft_id,
            "idea": idea,
            "headline": "",
            "caption": "",
            "hashtags": "",
            "alt_text": "",
            "image_prompt": "",
            "canvas": "portrait",
            "use_logo": True,
            "logo_position": "bottom_right",
            "media_type": "image",
            "image_template": "",
            "image_style": "warm",
            "image_custom": dict(DEFAULT_IMAGE_CUSTOM),
            "image_inputs": {},
            "carousel": [],
            "publish_at_local": None,
            "server_id": None,
            "status": "draft",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json(self.drafts / f"{draft_id}.json", draft)
        return draft

    def load_draft(self, draft_id: str) -> dict:
        path = self.drafts / f"{self._require_id(draft_id)}.json"
        if not path.exists():
            raise KeyError("Entwurf nicht gefunden.")
        return self._read_json(path)

    def list_drafts(self) -> list[dict]:
        drafts = [self._read_json(path) for path in self.drafts.glob("*.json")]
        return sorted(drafts, key=lambda item: item.get("updated_at", ""), reverse=True)

    def update_draft(self, draft_id: str, **fields) -> dict:
        draft = self.load_draft(draft_id)
        unknown = set(fields) - DRAFT_FIELDS
        if unknown:
            raise ValueError("Ungültiges Entwurfsfeld.")
        for name in {"idea", "headline", "caption", "hashtags", "alt_text", "image_prompt"} & fields.keys():
            if not isinstance(fields[name], str):
                raise ValueError("Bitte gib einen gültigen Text ein.")
        if "canvas" in fields and fields["canvas"] not in {"portrait", "square"}:
            raise ValueError("Bitte wähle Porträt oder Quadrat.")
        if "use_logo" in fields and not isinstance(fields["use_logo"], bool):
            raise ValueError("Ungültige Logo-Auswahl.")
        if "logo_position" in fields and fields["logo_position"] not in LOGO_POSITIONS:
            raise ValueError("Bitte wähle eine gültige Logo-Position.")
        if "media_type" in fields and fields["media_type"] not in {"image", "carousel", "video"}:
            raise ValueError("Bitte wähle Bild, Karussell oder Video.")
        if "image_template" in fields and (not isinstance(fields["image_template"], str) or len(fields["image_template"]) > 80):
            raise ValueError("Ungültige Bildvorlage.")
        if "image_style" in fields and fields["image_style"] not in IMAGE_STYLES:
            raise ValueError("Ungültige Farbwelt.")
        if "image_custom" in fields:
            fields["image_custom"] = validate_image_custom(fields["image_custom"])
        if "image_inputs" in fields:
            inputs = fields["image_inputs"]
            if (not isinstance(inputs, dict) or len(inputs) > 12 or
                    any(not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]{1,32}", key)
                        or not isinstance(value, str) or len(value) > 500 for key, value in inputs.items())):
                raise ValueError("Ungültige Angaben für die Bildvorlage.")
        if "carousel_alts" in fields:
            alts = fields.pop("carousel_alts")
            known = {item["id"]: item for item in draft.get("carousel", [])}
            if (not isinstance(alts, dict) or not set(alts).issubset(known)
                    or any(not isinstance(text, str) or len(text) > 1000 for text in alts.values())):
                raise ValueError("Ungültige Alternativtexte für das Karussell.")
            for item_id, text in alts.items():
                known[item_id]["alt_text"] = text
        draft.update(fields)
        draft["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(self.drafts / f"{draft_id}.json", draft)
        return draft

    def delete_draft(self, draft_id: str) -> None:
        draft = self.load_draft(draft_id)
        if draft.get("server_id"):
            raise ValueError("Dieser Beitrag wurde bereits an den Server übertragen.")
        for path in self.drafts.glob(f"{self._require_id(draft_id)}.*"):
            path.unlink(missing_ok=True)

    def save_media_state(self, draft):
        self._write_json(self.drafts / f"{self._require_id(draft['id'])}.json", draft)

    def media_path(self, draft_id, item_id, kind="original"):
        if kind not in {"original", "preview"}:
            raise ValueError("Ungültiges Bild.")
        return self.drafts / f"{self._require_id(draft_id)}.{self._require_id(item_id)}.{kind}.jpg"

    def add_carousel_image(self, draft_id, data, preview):
        draft = self.load_draft(draft_id)
        items = draft.setdefault("carousel", [])
        if len(items) >= 10:
            raise ValueError("Ein Karussell kann höchstens zehn Bilder enthalten.")
        item_id = secrets.token_hex(16)
        self.media_path(draft_id, item_id).write_bytes(data)
        self.media_path(draft_id, item_id, "preview").write_bytes(preview)
        items.append({"id": item_id, "alt_text": ""})
        self.save_media_state(draft)
        return draft

    def video_path(self, draft_id):
        return self.drafts / f"{self._require_id(draft_id)}.video.mp4"

    def _image_path(self, draft_id: str, kind: str) -> Path:
        return self.drafts / f"{self._require_id(draft_id)}.{kind}.jpg"

    def save_original_image(self, draft_id: str, data: bytes) -> Path:
        path = self._image_path(draft_id, "original")
        path.write_bytes(data)
        return path

    def original_image(self, draft_id: str) -> bytes:
        return self._image_path(draft_id, "original").read_bytes()

    def save_preview(self, draft_id: str, data: bytes) -> Path:
        path = self._image_path(draft_id, "preview")
        path.write_bytes(data)
        return path

    def preview(self, draft_id: str) -> bytes:
        return self._image_path(draft_id, "preview").read_bytes()

    def has_preview(self, draft_id: str) -> bool:
        return self._image_path(draft_id, "preview").exists()
