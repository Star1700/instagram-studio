import http.client
import json
import threading
from http.server import ThreadingHTTPServer

from studio.store import Store
from studio.web import Handler, RequestHandler, StudioApp


def test_local_api_rejects_foreign_sites_and_rebinding(tmp_path):
    app = StudioApp(Store(tmp_path), {"server_base_url": "https://example.test"})
    class LocalHandler(RequestHandler):
        application = Handler(app)
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    def request(headers):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request("POST", "/api/drafts", b'{"idea":"Safe local request"}', headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
    try:
        assert request({"Content-Type": "application/json"})[0] == 403
        assert request({"X-Studio-Request": "1", "Origin": "https://foreign.example"})[0] == 403
        assert request({"X-Studio-Request": "1", "Host": f"foreign.example:{port}"})[0] == 403
        assert app.store.list_drafts() == []
        assert request({"X-Studio-Request": "1", "Origin": f"http://127.0.0.1:{port}"})[0] == 201
        assert len(app.store.list_drafts()) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
