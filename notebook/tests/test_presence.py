import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from studio.presence import Presence
from studio.store import Store
from studio.web import Handler, RequestHandler, StudioApp, serve_until_closed


def test_presence_waits_for_first_tab_and_expires_crashed_tabs():
    now = [0.0]
    presence = Presence(clock=lambda: now[0], startup_grace=20, stale_after=30, close_grace=5)
    now[0] = 19
    assert not presence.should_stop()
    tab = "a" * 32
    presence.update(tab, "touch")
    now[0] = 30
    assert not presence.should_stop()
    now[0] = 50
    assert not presence.should_stop()
    now[0] = 55
    assert presence.should_stop()


def test_presence_handles_multiple_tabs_and_reload_grace():
    now = [0.0]
    presence = Presence(clock=lambda: now[0], startup_grace=20, stale_after=30, close_grace=5)
    first, second, reloaded = "a" * 32, "b" * 32, "c" * 32
    presence.update(first, "touch")
    presence.update(second, "touch")
    presence.update(first, "leave")
    now[0] = 6
    assert not presence.should_stop()
    presence.update(second, "leave")
    now[0] = 9
    assert not presence.should_stop()
    presence.update(reloaded, "touch")
    now[0] = 20
    assert not presence.should_stop()
    presence.update(reloaded, "leave")
    now[0] = 25
    assert presence.should_stop()
    with pytest.raises(ValueError):
        presence.update("wrong-id", "touch")


def test_http_server_exits_after_last_tab_closes(tmp_path):
    app = StudioApp(Store(tmp_path), {})
    app.presence = Presence(startup_grace=2, stale_after=1, close_grace=0.12)
    RequestHandler.application = Handler(app)
    server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
    worker = threading.Thread(target=serve_until_closed, args=(server, app.presence, 0.02), daemon=True)
    worker.start()

    def post(tab_id, action):
        request = Request(f"http://127.0.0.1:{server.server_port}/api/presence",
                          data=json.dumps({"tab_id": tab_id, "action": action}).encode(),
                          headers={"Content-Type": "application/json", "X-Studio-Request": "1"}, method="POST")
        with urlopen(request, timeout=2) as response:
            assert response.status == 204

    post("a" * 32, "touch")
    post("b" * 32, "touch")
    post("a" * 32, "leave")
    time.sleep(0.18)
    assert worker.is_alive()
    post("b" * 32, "leave")
    worker.join(timeout=2)
    assert not worker.is_alive()


def test_open_connection_closes_server_when_browser_disconnects(tmp_path, monkeypatch):
    app = StudioApp(Store(tmp_path), {})
    app.presence = Presence(startup_grace=2, stale_after=5, close_grace=0.12)
    RequestHandler.application = Handler(app)
    monkeypatch.setattr(RequestHandler, "presence_ping_interval", 0.05)
    server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
    worker = threading.Thread(target=serve_until_closed, args=(server, app.presence, 0.02), daemon=True)
    worker.start()
    request = Request(f"http://127.0.0.1:{server.server_port}/api/presence/stream",
                      data=json.dumps({"tab_id": "a" * 32}).encode(),
                      headers={"Content-Type": "application/json", "X-Studio-Request": "1"}, method="POST")
    with urlopen(request, timeout=2) as response:
        assert response.status == 200
        assert response.read(10) == b": studio\n\n"
    worker.join(timeout=2)
    assert not worker.is_alive()


def test_heartbeat_is_not_blocked_by_a_long_text_generation(tmp_path):
    app = StudioApp(Store(tmp_path), {})
    locked, release = threading.Event(), threading.Event()

    def hold_generation_lock():
        with app.account_lock:
            locked.set()
            release.wait(timeout=2)

    holder = threading.Thread(target=hold_generation_lock)
    holder.start()
    assert locked.wait(timeout=1)
    try:
        status, _, _ = app.handle("POST", "/api/presence",
                                  json.dumps({"tab_id": "a" * 32, "action": "touch"}).encode())
        assert holder.is_alive()
        assert status == 204 and "a" * 32 in app.presence.tabs
    finally:
        release.set()
        holder.join(timeout=2)
