"""An installation-wide library of named writing profiles, without account assets."""
import secrets

from .settings import PROFILE_FIELDS, validate_profile


class WritingProfiles:
    def __init__(self, store):
        self.store = store
        self.path = store.root / "writing-profiles.json"

    def all(self):
        return self.store._read_json(self.path).get("profiles", []) if self.path.exists() else []

    def save(self, values, profile_id=None):
        profile = validate_profile({"language": "Deutsch", "emoji": "Wenige Emojis", "effort": "high", **values}, {})
        name = profile.get("name", "").strip()
        if not name or len(name) > 80:
            raise ValueError("Gib deinem Schreibprofil einen Namen mit höchstens 80 Zeichen.")
        profiles = self.all()
        existing = next((item for item in profiles if item["id"] == profile_id), None)
        if profile_id and not existing:
            raise ValueError("Dieses Schreibprofil wurde nicht gefunden.")
        if any(item["name"].casefold() == name.casefold() and item is not existing for item in profiles):
            raise ValueError("Dieser Profilname ist schon vergeben. Wähle einen anderen Namen oder lade das vorhandene Profil.")
        if not existing and len(profiles) >= 100:
            raise ValueError("Du kannst höchstens 100 Schreibprofile speichern.")
        item = {"id": profile_id or secrets.token_hex(16), "name": name,
                "values": {key: profile.get(key, "") for key in PROFILE_FIELDS}}
        profiles = [item if old is existing else old for old in profiles]
        if not existing:
            profiles.append(item)
        self.store._write_json(self.path, {"profiles": profiles})
        return item

    def get(self, profile_id):
        item = next((item for item in self.all() if item["id"] == profile_id), None)
        if item is None:
            raise ValueError("Dieses Schreibprofil wurde nicht gefunden.")
        return item
