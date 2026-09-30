import hashlib
import json
from pathlib import Path

import pytest

from studio.accounts import Accounts
from studio.store import Store
from studio.web import StudioApp
from studio import settings
from studio.codex_text import generate


class OAuthServer:
    def start_oauth(self, state, verifier_hash, key_hash):
        self.state, self.verifier_hash, self.key_hash = state, verifier_hash, key_hash
        return {"url": "https://www.instagram.com/oauth/authorize?state=" + state}

    def poll_oauth(self, state, verifier):
        assert state == self.state
        assert hashlib.sha256(verifier.encode()).hexdigest() == self.verifier_hash
        return {"state": "connected", "installation_id": "a" * 32,
                "account": {"id": "123", "username": "friend"}}

    def pull_token(self):
        return {"user_id": "123", "access_token": "private-token", "expires_at": "2099-01-01T00:00:00Z"}


def test_new_installation_needs_no_app_secret_and_preserves_setup(tmp_path):
    config = {"server_base_url": "https://example.test"}
    base = Store(tmp_path)
    profile = base.load_profile()
    base.save_profile({**profile, "name": "Lea", "logo_path": "logo.bin"})
    (tmp_path / "logo.bin").write_bytes(b"logo")
    accounts = Accounts(config, base, lambda: None)
    server = OAuthServer()
    accounts.api = lambda account_id=None: server
    started = accounts.start()
    assert set(started) == {"url"}
    result = accounts.poll()
    assert result["account"]["id"] == "123"
    assert accounts.store().load_profile()["name"] == "Lea"
    assert (accounts.store().root / "logo.bin").read_bytes() == b"logo"
    assert hashlib.sha256(config["installation_key"].encode()).hexdigest() == server.key_hash
    assert "private-token" not in json.dumps(accounts.public())
    assert "oauth_pending" not in config
    assert "instagram_app_secret" not in config


def test_account_switch_keeps_drafts_profiles_and_stale_tab_separate(tmp_path):
    config = {"accounts": {"123": {"username": "one"}, "456": {"username": "two"}}, "active_account_id": "123"}
    app = StudioApp(Store(tmp_path), config)
    draft = app.store.create_draft("Only account one")
    app.store.save_profile({"name": "One"})
    app.accounts.select("456")
    assert app.store.list_drafts() == []
    assert app.store.load_profile()["name"] != "One"
    status, body, _ = app.handle("POST", f"/api/drafts/{draft['id']}/send", b'{"when":"now"}',
                                 {"X-Studio-Local-Account": "123"})
    assert status == 409 and "anderen Fenster" in body.decode()
    assert app.handle("PATCH", "/api/profile", b'{"name":"Wrong"}', {"X-Studio-Local-Account": "123"})[0] == 409
    app.accounts.select("123")
    assert app.store.load_draft(draft["id"])["idea"] == "Only account one"
    with pytest.raises(ValueError):
        app.accounts.select("../456")


def test_legacy_owner_keeps_existing_drafts_and_no_secrets_in_profile(tmp_path):
    store = Store(tmp_path)
    draft = store.create_draft("Old draft")
    config = {"instagram_user_id": "123", "instagram_access_token": "secret-token", "instagram_app_secret": "app-secret",
              "upload_password": "upload-secret", "ftp": {"password": "ftp-secret"}}
    app = StudioApp(store, config)
    assert app.store.root == store.root
    assert app.store.load_draft(draft["id"])["idea"] == "Old draft"
    status, body, _ = app.handle("GET", "/api/profile")
    assert status == 200
    assert not any(value.encode() in body for value in ("secret-token", "app-secret", "upload-secret", "ftp-secret"))


def test_model_selection_is_validated_and_passed_only_to_text_run(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "model_catalogue", lambda: [{"id": "small-test", "efforts": ["low", "high"]}])
    profile = settings.validate_profile({"name": "Lea", "model": "small-test", "effort": "low", "setup_complete": True}, {})
    with pytest.raises(ValueError):
        settings.validate_profile({"model": "not-available"}, profile)
    with pytest.raises(ValueError):
        settings.validate_profile({"effort": "ultra"}, profile)
    with pytest.raises(ValueError):
        settings.validate_profile({"logo_path": "../private"}, profile)
    seen = {}
    def runner(argv, cwd, prompt):
        seen.update(argv=argv, cwd=cwd, prompt=prompt)
        return json.dumps(dict(headline="Test", caption="Caption", hashtags=""))
    generate(profile, {"idea": "Hello"}, None, runner)
    assert seen["argv"][seen["argv"].index("--model") + 1] == "small-test"
    assert 'model_reasoning_effort="low"' in seen["argv"]
    assert Path(seen["cwd"]) != Path.cwd()


def test_new_installation_cannot_send_before_connection(tmp_path):
    app = StudioApp(Store(tmp_path), {"server_base_url": "https://example.test"})
    draft = app.store.create_draft("Test")
    assert app.handle("POST", f"/api/drafts/{draft['id']}/send", b'{"when":"now"}')[0] == 409


@pytest.mark.parametrize("available,configured,profile,expected", [
    (["gpt-6-astra", "gpt-6-sol", "gpt-6.1-sol"], "gpt-6-astra", {}, "gpt-6.1-sol"),
    (["gpt-6-astra", "gpt-6-sol"], "gpt-6-astra", {}, "gpt-6-sol"),
    (["first-model", "configured-model"], "configured-model", {}, "configured-model"),
    (["first-model"], "removed-model", {}, "first-model"),
    ([], "removed-model", {}, "Codex-Standard"),
    (["gpt-6.1-sol"], "", {"model": "removed-model"}, "gpt-6.1-sol"),
    (["gpt-6.1-sol", "chosen-model"], "", {"model": "chosen-model"}, "chosen-model"),
])
def test_model_default_and_catalogue_fallback(monkeypatch, tmp_path, available, configured, profile, expected):
    monkeypatch.setattr(settings, "codex_home", lambda: tmp_path)
    (tmp_path / "config.toml").write_text(f'model = "{configured}"\n', encoding="utf-8")
    monkeypatch.setattr(settings, "model_catalogue", lambda: [
        {"id": model, "efforts": ["low", "high"]} for model in available
    ])
    assert settings.codex_settings(profile) == {"model": expected, "effort": "high"}


def test_catalogue_changes_are_read_again_and_effort_remains_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "codex_home", lambda: tmp_path)
    cache_path = tmp_path / "models_cache.json"
    def write_model(slug, efforts):
        cache_path.write_text(json.dumps({"models": [{
            "slug": slug, "visibility": "list", "supported_reasoning_levels": [
                {"effort": effort} for effort in efforts
            ]
        }]}), encoding="utf-8")
    write_model("gpt-6.1-sol", ["low", "high"])
    assert settings.codex_settings({}) == {"model": "gpt-6.1-sol", "effort": "high"}
    write_model("new-model", ["medium"])
    assert settings.codex_settings({"model": "gpt-6.1-sol", "effort": "high"}) == {
        "model": "new-model", "effort": "medium"
    }
