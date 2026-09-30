"""Editable writing preferences and the locally advertised Codex model catalogue."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib

PROFILE_FIELDS = ("name", "language", "niche", "tone", "avoid", "emoji", "hashtags", "model", "effort")
PRESETS = {
    "fitness": {"label": "Fitness und Alltag", "niche": "Fitness und ein aktiver Alltag ohne Leistungsdruck",
                "avoid": "Keine Trainings-, Gesundheits- oder Diätversprechen"},
    "personal": {"label": "Persönlicher Alltag", "niche": "Persönliche Einblicke und kleine Momente aus meinem Alltag",
                 "avoid": "Keine erfundenen Erfahrungen"},
    "family": {"label": "Alltag als Mama", "niche": "Ehrlicher Familienalltag für Eltern, die sich wiedererkennen möchten",
               "avoid": "Keine erfundenen Erlebnisse, keine Erziehungsversprechen"},
    "creative": {"label": "Kreativ und Kultur", "niche": "Meine kreative Arbeit und die Geschichten hinter meinen Projekten",
                 "avoid": "Keine unbelegten Behauptungen"},
    "business": {"label": "Beruf und Unternehmen", "niche": "Einblicke in meine Arbeit und hilfreiche Beiträge für meine Kundschaft",
                 "avoid": "Keine übertriebenen Erfolgsversprechen"},
}
TONES = ["direkt und freundlich", "ruhig und persönlich", "locker und humorvoll", "sachlich und klar", "motivierend ohne Druck", "tiefgründig und nachdenklich"]
LANGUAGES = {"Deutsch", "Englisch"}
EMOJI_CHOICES = {"Keine Emojis", "Wenige Emojis", "Einige Emojis", "Emojis im Überfluss"}


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def model_catalogue() -> list[dict]:
    try:
        cached = json.loads((codex_home() / "models_cache.json").read_text(encoding="utf-8"))
        return [{"id": item["slug"], "name": item.get("display_name", item["slug"]),
                 "efforts": [level["effort"] for level in item.get("supported_reasoning_levels", [])]}
                for item in cached.get("models", [])
                if item.get("visibility") == "list" and re.fullmatch(r"[a-zA-Z0-9._-]+", item.get("slug", ""))]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def codex_settings(profile: dict) -> dict:
    try:
        configured = tomllib.loads((codex_home() / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        configured = {}
    catalogue = {item["id"]: item for item in model_catalogue()}
    preferred = next((model for model in ("gpt-6.1-sol", "gpt-6-sol") if model in catalogue),
                     configured.get("model", ""))
    if preferred not in catalogue:
        preferred = next(iter(catalogue), "")
    model = profile.get("model") if profile.get("model") in catalogue else preferred
    efforts = catalogue.get(model, {}).get("efforts", ["low", "medium", "high"])
    requested = profile.get("effort") or "high"
    effort = requested if requested in efforts else ("high" if "high" in efforts else (efforts[0] if efforts else "medium"))
    return {"model": model or "Codex-Standard", "effort": effort}


def validate_profile(values: dict, previous: dict) -> dict:
    if set(values) - set(PROFILE_FIELDS) - {"setup_complete"}:
        raise ValueError("Unbekannte Profileinstellung.")
    updated = dict(previous)
    for field in PROFILE_FIELDS:
        if field in values:
            if not isinstance(values[field], str) or len(values[field]) > 3000:
                raise ValueError("Bitte verwende gültige Texte mit höchstens 3000 Zeichen.")
            cleaned = values[field].strip()
            updated[field] = (cleaned or "Wenige Emojis") if field == "emoji" else cleaned
    if "language" in values and updated["language"] not in LANGUAGES:
        raise ValueError("Wähle Deutsch oder Englisch.")
    if "emoji" in values and updated["emoji"] not in EMOJI_CHOICES:
        raise ValueError("Bitte wähle eine Emoji-Menge aus.")
    model, effort = updated.get("model", ""), updated.get("effort", "")
    catalogue = {item["id"]: item for item in model_catalogue()}
    if model and model not in catalogue:
        raise ValueError("Dieses Modell wird von Codex auf diesem PC noch nicht angeboten. Aktualisiere die Modellauswahl oder wähle Codex-Standard.")
    allowed = catalogue[model]["efforts"] if model else ["low", "medium", "high"]
    if effort and effort not in allowed:
        raise ValueError("Dieser Denkaufwand passt nicht zum gewählten Modell.")
    if "setup_complete" in values:
        if values["setup_complete"] is not True or not updated.get("name"):
            raise ValueError("Trage bitte deinen Profilnamen ein.")
        updated["setup_complete"] = True
    return updated


def desktop_path() -> Path:
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                return Path(os.path.expandvars(winreg.QueryValueEx(key, "Desktop")[0]))
        except OSError:
            pass
    return Path.home() / "Desktop"


def runtime_health() -> dict:
    executable = shutil.which("codex")
    signed_in = False
    if executable:
        try:
            result = subprocess.run([executable, "login", "status"], capture_output=True, timeout=12,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            signed_in = result.returncode == 0 and b"chatgpt" in (result.stdout + result.stderr).lower()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {"python": sys.version_info >= (3, 11), "packages": True,
            "codex": bool(executable), "chatgpt_login": signed_in,
            "shortcut": (desktop_path() / "Studio.lnk").exists()}
