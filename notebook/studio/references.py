"""Persistent user-selected reference folder; images never leave through this module."""
from pathlib import Path
import json
import os
import subprocess
import sys


def default_folder():
    documents = Path.home() / "Documents"
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                documents = Path(os.path.expandvars(winreg.QueryValueEx(key, "Personal")[0]))
        except OSError:
            pass
    return documents / "Studio" / "Referenzen"


class References:
    def __init__(self, store):
        self.store, self.path = store, store.root / "preferences.json"

    def folder(self):
        data = self.store._read_json(self.path) if self.path.exists() else {}
        return Path(data["reference_folder"]) if data.get("reference_folder") else default_folder()

    def set(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Bitte wähle einen vorhandenen Referenzordner.")
        path = Path(value.strip()).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("Bitte gib den vollständigen Pfad zu einem vorhandenen Ordner an.")
        data = self.store._read_json(self.path) if self.path.exists() else {}
        data["reference_folder"] = str(path.resolve())
        self.store._write_json(self.path, data)
        return self.folder()

    def open(self, opener):
        path = self.folder()
        if path == default_folder():
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise ValueError("Der Referenzordner ist nicht mehr erreichbar. Wähle ihn bitte erneut.")
        opener(path)

    def choose(self):
        try:
            result = subprocess.run([sys.executable, "-m", "studio.folder_picker", str(self.folder())],
                                    capture_output=True, timeout=180,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            value = json.loads(result.stdout.decode("utf-8")) if result.returncode == 0 else None
            if value is None:
                raise ValueError
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise ValueError("Die Ordnerauswahl konnte nicht geöffnet werden. Trage den Ordnerpfad direkt ein.") from None
        if value:
            self.set(value)
        return bool(value)
