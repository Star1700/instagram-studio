"""Private account state; only whitelisted identities reach the browser."""
import hashlib
import re
import shutil
import secrets
import time

from .oauth import identity, meta_http
from .server_api import ServerApi
from .store import Store


class Accounts:
    def __init__(self, config: dict, base_store: Store, persist, http=meta_http):
        self.config, self.base, self.persist, self.http = config, base_store, persist, http
        config.setdefault("accounts", {})
        legacy_id = config.get("instagram_user_id", "")
        if legacy_id and legacy_id not in config["accounts"] and config.get("instagram_access_token"):
            config["accounts"][legacy_id] = {
                "id": legacy_id, "username": base_store.load_profile().get("handle", ""), "legacy": True,
                "access_token": config["instagram_access_token"],
                "expires_at": config.get("instagram_token_expires_at", ""),
            }
            config.setdefault("active_account_id", legacy_id)
            persist()
        if config["accounts"].get(legacy_id, {}).get("legacy"):
            profile = base_store.load_profile()
            if "setup_complete" not in profile:
                profile["name"] = profile.get("name") or profile.get("handle") or "Mein Profil"
                profile["setup_complete"] = True
                base_store.save_profile(profile)

    @property
    def active_id(self) -> str:
        return self.config.get("active_account_id", "")

    def api(self, account_id=None):
        return ServerApi(self.config.get("server_base_url", "https://www.starseven.at"),
                         self.config.get("installation_key") or self.config.get("upload_password", ""), account_id=self.active_id if account_id is None else account_id)

    def store(self) -> Store:
        record = self.config["accounts"].get(self.active_id)
        if record is None or record.get("legacy"):
            return self.base
        return Store(self.base.root / "accounts" / self.active_id)

    def public(self) -> dict:
        return {"active_account_id": self.active_id,
                "accounts": [{"id": key, "username": value.get("username", ""),
                              "expires_at": value.get("expires_at", "")}
                             for key, value in self.config["accounts"].items()]}

    def select(self, account_id: str):
        if account_id not in self.config["accounts"]:
            raise ValueError("Dieses Konto ist auf diesem PC noch nicht verbunden.")
        self.config["active_account_id"] = account_id
        self.persist()

    def start(self):
        state, verifier = secrets.token_hex(32), secrets.token_hex(32)
        key = self.config.get("installation_key") or secrets.token_hex(32)
        result = self.api("").start_oauth(state, hashlib.sha256(verifier.encode()).hexdigest(),
                                         hashlib.sha256(key.encode()).hexdigest())
        self.config["oauth_pending"] = {"state": state, "verifier": verifier, "key": key, "started_at": time.time()}
        self.persist()
        return {"url": result["url"]}

    def poll(self):
        pending = self.config.get("oauth_pending")
        if not pending:
            return {"state": "idle"}
        if time.time() - pending["started_at"] > 1800:
            self.config.pop("oauth_pending", None); self.persist()
            raise RuntimeError("Die Anmeldung ist abgelaufen. Starte Instagram verbinden erneut.")
        response = self.api("").poll_oauth(pending["state"], pending["verifier"])
        if response is None:
            return {"state": "waiting"}
        if response.get("state") == "denied":
            self.config.pop("oauth_pending", None); self.persist()
            raise RuntimeError("Die Instagram-Freigabe wurde abgebrochen. Starte die Verbindung erneut.")
        who = response.get("account", {})
        account_id = who.get("id", "")
        tenant = response.get("installation_id", "")
        if (response.get("state") != "connected" or not re.fullmatch(r"[0-9]{1,32}", account_id)
                or not re.fullmatch(r"owner|[a-f0-9]{32}", tenant) or not isinstance(who.get("username"), str)):
            raise RuntimeError("Instagram hat keine gültige Verbindung bestätigt.")
        if tenant != "owner":
            self.config["installation_key"] = pending["key"]
        self.config["installation_id"] = tenant
        self.persist()
        token = self.api(account_id).pull_token()
        if token is None or token["user_id"] != account_id:
            raise RuntimeError("Die Verbindung konnte noch nicht auf diesen PC übernommen werden. Bitte prüfe sie erneut.")
        first = not self.config["accounts"]
        previous = self.config["accounts"].get(account_id, {})
        self.config["accounts"][account_id] = {**previous, **who, "access_token": token["access_token"],
                                              "expires_at": token.get("expires_at", "")}
        self.select(account_id)
        destination = self.store()
        if not (destination.root / "profile.json").exists() and first:
            profile = self.base.load_profile()
            logo = self.base.root / profile.get("logo_path", "")
            if logo.is_file() and logo.parent == self.base.root:
                shutil.copyfile(logo, destination.root / "logo.bin")
                profile["logo_path"] = "logo.bin"
            else:
                profile["logo_path"] = ""
            profile["references"] = {}
            destination.save_profile(profile)
        profile = destination.load_profile()
        profile["handle"] = who["username"]
        destination.save_profile(profile)
        self.config.pop("oauth_pending", None); self.persist()
        return {"state": "connected", "account": who}

    def check(self):
        if not self.active_id:
            raise RuntimeError("Verbinde zuerst dein Instagram-Konto.")
        token = self.api().pull_token()
        if token is None or token["user_id"] != self.active_id:
            raise RuntimeError("Die Instagram-Erlaubnis fehlt oder ist abgelaufen. Verbinde dieses Konto erneut.")
        who = identity(token["access_token"], self.http)
        if who["id"] != self.active_id:
            raise RuntimeError("Die Instagram-Verbindung passt nicht zum gewählten Konto.")
        record = self.config["accounts"][self.active_id]
        record.update(who, access_token=token["access_token"], expires_at=token.get("expires_at", ""))
        profile = self.store().load_profile(); profile["handle"] = who["username"]; self.store().save_profile(profile)
        self.persist()
        return who
