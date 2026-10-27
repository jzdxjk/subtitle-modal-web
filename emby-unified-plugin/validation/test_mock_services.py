import importlib.util
import base64
import http.client
import json
from pathlib import Path
import sys
import socket
import struct
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def mock_module():
    path = Path(__file__).with_name("mock_services.py")
    if not path.exists():
        raise AssertionError("isolated fixture services have not been implemented")
    if "mock_services" not in sys.modules:
        spec = importlib.util.spec_from_file_location("mock_services", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules["mock_services"]


class MockServiceTests(unittest.TestCase):
    def setUp(self):
        module = mock_module()
        temporary_root = Path(__file__).parent / ".test-temp"
        temporary_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.temporary.name).resolve()
        self.state = module.MockState(self.root)
        self.server = module.make_http_server("127.0.0.1", 0, self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.base + path, data=data, headers={"Content-Type": "application/json", **(headers or {})})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_fallback_pool_returns_all_six_and_only_sixth_download_succeeds(self):
        module = mock_module()
        result = self.request("/pool/fallback/api/v1/subtitles/search?match=work&codes=ABP-192&duration=12")
        self.assertEqual(len(result["items"]), 6)
        self.assertEqual([item["size_bytes"] for item in result["items"]], sorted(
            [item["size_bytes"] for item in result["items"]], reverse=True))
        for item in result["items"][:5]:
            with self.assertRaises(HTTPError) as raised:
                urlopen(self.base + "/pool/fallback" + item["download_url"], timeout=5)
            self.assertEqual(raised.exception.code, 404)
        last = result["items"][-1]
        with urlopen(self.base + "/pool/fallback" + last["download_url"], timeout=5) as response:
            data = response.read()
        self.assertEqual(module.hashlib.sha256(data).hexdigest(), last["sha256"])

    def test_cloud_done_writes_only_owned_fixture_and_records_refresh_success(self):
        video = self.root / "4.10.2.0/media/videos/FNS-192-CD2-1080p.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"independent fixture")
        job = self.request("/cloud/4.10.2.0/api/plugin/jobs", {
            "input_path": str(video), "emby_item_id": "42", "display_title": "FNS-192", "av_code": "FNS-192",
        }, {"X-API-Token": "private-test-auth"})
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["refresh_state"], "pending")
        self.assertTrue(video.with_suffix(".zh-CN.srt").is_file())
        self.request("/cloud/4.10.2.0/api/plugin/jobs/" + job["id"] + "/refresh-result", {"state": "success"})
        jobs = self.request("/cloud/4.10.2.0/api/plugin/jobs")
        self.assertEqual(jobs[0]["refresh_state"], "success")
        self.assertNotIn("private-test-auth", json.dumps(self.request("/__test/events")))

    def test_cloud_rejects_any_input_outside_the_owned_fixture_directory(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("/cloud/4.10.2.0/api/plugin/jobs", {
                "input_path": "/volume1/docker/emby/config/production.mp4", "emby_item_id": "42",
            })
        self.assertEqual(raised.exception.code, 400)

    def start_proxy(self, name):
        factory = getattr(mock_module(), name, None)
        self.assertTrue(callable(factory), "isolated authenticated proxy has not been implemented")
        server = factory("127.0.0.1", 0, self.state,
                         ("127.0.0.1", self.server.server_port), "validation", "private-proxy-password")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_http_proxy_requires_auth_forwards_fixture_and_rejects_other_targets(self):
        port = self.start_proxy("make_http_proxy")
        auth = "Basic " + base64.b64encode(b"validation:private-proxy-password").decode()
        for url, headers, expected in [
            (self.base + "/health", {}, 407),
            ("http://127.0.0.1:1/production", {"Proxy-Authorization": auth}, 403),
            (self.base + "/health", {"Proxy-Authorization": auth}, 200),
        ]:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", url, headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, expected)
            response.read()
            connection.close()
        self.assertNotIn("private-proxy-password", json.dumps(self.state.events))

    def test_socks5_proxy_authenticates_and_tunnels_only_fixture_target(self):
        port = self.start_proxy("make_socks_proxy")
        for target, expected in [(1, 2), (self.server.server_port, 0)]:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
                connection.sendall(b"\x05\x01\x02")
                self.assertEqual(connection.recv(2), b"\x05\x02")
                username, password = b"validation", b"private-proxy-password"
                connection.sendall(b"\x01" + bytes([len(username)]) + username + bytes([len(password)]) + password)
                self.assertEqual(connection.recv(2), b"\x01\x00")
                connection.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", target))
                reply = connection.recv(10)
                self.assertEqual(reply[1], expected)
                if expected == 0:
                    connection.sendall(b"GET /health HTTP/1.0\r\nHost: fixture\r\n\r\n")
                    response = http.client.HTTPResponse(connection)
                    response.begin()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read())["ok"])
        self.assertNotIn("private-proxy-password", json.dumps(self.state.events))


if __name__ == "__main__":
    unittest.main()
