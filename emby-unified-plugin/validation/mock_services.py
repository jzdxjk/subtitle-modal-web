#!/usr/bin/env python3
"""Local-only subtitle/cloud/update fixtures; never reads production media."""

import argparse
import base64
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import secrets
import select
import socket
import socketserver
import struct
import threading
import time
from urllib.parse import urlsplit
import uuid

from emby_validation import CASES, ROOT, ensure_root, write_private


def subtitle_bytes(index=6):
    return ("1\n00:00:00,000 --> 00:00:11,000\n隔离验收字幕" + "，完整时间轴" * (7 - index) + "。\n").encode("utf-8")


class MockState:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self.jobs = {version: [] for version in CASES}
        self.events = []

    def record(self, method, path, **extra):
        with self.lock:
            self.events.append({"Method": method, "Path": urlsplit(path).path, **extra})


def make_http_server(host, port, state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, value, content_type="application/json"):
            data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def dispatch(self):
            url = urlsplit(self.path)
            state.record(self.command, url.path)
            try:
                if self.command == "GET" and url.path == "/health":
                    return self.reply(200, {"ok": True, "fixture": True})
                if self.command == "GET" and url.path == "/__test/events":
                    with state.lock:
                        return self.reply(200, list(state.events))
                cloud = re.fullmatch(r"/cloud/([^/]+)/api/plugin/jobs(?:/([0-9a-f-]+)/refresh-result)?", url.path)
                if cloud and cloud[1] in CASES:
                    version, identifier = cloud.groups()
                    with state.lock:
                        jobs = state.jobs[version]
                        if self.command == "GET" and not identifier:
                            return self.reply(200, list(jobs))
                        if self.command == "POST":
                            length = int(self.headers.get("Content-Length", "0"))
                            if not 0 < length <= 65536:
                                return self.reply(400, {"error": "invalid_fixture_payload"})
                            payload = json.loads(self.rfile.read(length))
                            if identifier:
                                job = next((job for job in jobs if job["id"] == identifier), None)
                                if job is None:
                                    return self.reply(404, {"error": "job_not_found"})
                                job["refresh_state"] = payload.get("state")
                                return self.reply(200, {"ok": True})
                            source = Path(payload.get("input_path", "")).resolve()
                            directory = state.root / version / "media" / "videos"
                            if (not source.is_relative_to(directory.resolve()) or source.suffix != ".mp4"
                                    or not source.is_file() or source.stat().st_size > 1024 * 1024):
                                return self.reply(400, {"error": "path_outside_owned_fixture"})
                            output = source.with_suffix(".zh-CN.srt")
                            if not output.exists():
                                output.write_bytes(subtitle_bytes())
                            job = {
                                "id": str(uuid.uuid4()), "emby_item_id": str(payload.get("emby_item_id", "")),
                                "display_title": str(payload.get("display_title", "隔离验收任务")),
                                "status": "done", "phase": "done", "progress": 100,
                                "message": "隔离字幕已写入，等待单项刷新", "refresh_state": "pending",
                                "created_at": time.time(), "updated_at": time.time(),
                            }
                            jobs.append(job)
                            return self.reply(200, job)
                if self.command == "GET" and url.path in ("/updates/update.json", "/updates/Emby.SubtitleAssistant.dll"):
                    filename = url.path.rsplit("/", 1)[1]
                    path = state.root / "artifacts" / filename
                    if path.is_file():
                        content_type = "application/json" if filename.endswith(".json") else "application/octet-stream"
                        return self.reply(200, path.read_bytes(), content_type)
                return self.reply(404, {"error": "fixture_route_not_found"})
            except (ValueError, OSError):
                return self.reply(400, {"error": "invalid_fixture_request"})

    return ThreadingHTTPServer((host, port), Handler)


def make_http_proxy(host, port, state, upstream, username, password):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, data=b"", content_type="text/plain"):
            self.send_response(status)
            if status == 407:
                self.send_header("Proxy-Authenticate", 'Basic realm="SubtitleAssistantValidation"')
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def do_CONNECT(self):
            state.record("CONNECT", "/", Proxy="HTTP", TargetAllowed=False)
            self.reply(403)

        def forward(self):
            try:
                value = self.headers.get("Proxy-Authorization", "")
                actual = base64.b64decode(value[6:], validate=True) if value.startswith("Basic ") else b""
                if not secrets.compare_digest(actual, (username + ":" + password).encode()):
                    return self.reply(407)
                target = urlsplit(self.path)
                if (target.scheme != "http" or (target.hostname, target.port or 80) != upstream
                        or target.username is not None or target.password is not None):
                    state.record(self.command, "/", Proxy="HTTP", TargetAllowed=False)
                    return self.reply(403)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 65536:
                    return self.reply(413)
                path = target.path or "/"
                if target.query:
                    path += "?" + target.query
                headers = {key: value for key, value in self.headers.items()
                           if key.lower() not in ("proxy-authorization", "proxy-connection", "connection")}
                state.record(self.command, path, Proxy="HTTP", TargetAllowed=True)
                connection = http.client.HTTPConnection(*upstream, timeout=15)
                try:
                    connection.request(self.command, path, body=self.rfile.read(length) if length else None, headers=headers)
                    response = connection.getresponse()
                    data = response.read()
                    self.reply(response.status, data, response.getheader("Content-Type", "application/octet-stream"))
                finally:
                    connection.close()
            except (OSError, ValueError, http.client.HTTPException):
                self.reply(502)

    return ThreadingHTTPServer((host, port), Handler)


def make_socks_proxy(host, port, state, upstream, username, password):
    def receive(connection, count):
        data = b""
        while len(data) < count:
            chunk = connection.recv(count - len(data))
            if not chunk:
                raise OSError("fixture SOCKS connection ended")
            data += chunk
        return data

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            connection = self.request
            connection.settimeout(15)
            try:
                version, count = receive(connection, 2)
                methods = receive(connection, count)
                if version != 5 or 2 not in methods:
                    connection.sendall(b"\x05\xff")
                    return
                connection.sendall(b"\x05\x02")
                auth_version, length = receive(connection, 2)
                actual_user = receive(connection, length)
                actual_password = receive(connection, receive(connection, 1)[0])
                authorized = auth_version == 1 and secrets.compare_digest(actual_user, username.encode()) \
                    and secrets.compare_digest(actual_password, password.encode())
                connection.sendall(b"\x01\x00" if authorized else b"\x01\x01")
                if not authorized:
                    return
                version, command, _reserved, address_type = receive(connection, 4)
                if address_type == 1:
                    address = socket.inet_ntoa(receive(connection, 4))
                elif address_type == 3:
                    address = receive(connection, receive(connection, 1)[0]).decode("ascii")
                elif address_type == 4:
                    address = socket.inet_ntop(socket.AF_INET6, receive(connection, 16))
                else:
                    return
                target_port = struct.unpack("!H", receive(connection, 2))[0]
                allowed = version == 5 and command == 1 and (address, target_port) == upstream
                state.record("CONNECT", "/", Proxy="SOCKS5", TargetAllowed=allowed)
                if not allowed:
                    connection.sendall(b"\x05\x02\x00\x01" + b"\x00" * 6)
                    return
                with socket.create_connection(upstream, timeout=15) as remote:
                    connection.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
                    while True:
                        readable, _, _ = select.select([connection, remote], [], [], 30)
                        if not readable:
                            return
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            (remote if source is connection else connection).sendall(data)
            except (OSError, ValueError):
                return

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    return Server((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19100)
    parser.add_argument("--http-proxy-port", type=int, default=19101)
    parser.add_argument("--socks-proxy-port", type=int, default=19102)
    args = parser.parse_args()
    address = ipaddress.ip_address(args.bind)
    if address.is_unspecified or not (address.is_private or address.is_loopback):
        raise ValueError("fixture service must bind loopback or the private Docker bridge address")
    ensure_root()
    state = MockState(ROOT)
    private_path = ROOT / "mock-session.json"
    credentials = json.loads(private_path.read_text()) if private_path.exists() else {
        "Username": "validation", "Password": secrets.token_urlsafe(32),
    }
    write_private(private_path, credentials)
    server = make_http_server(args.bind, args.port, state)
    for factory, port in [(make_http_proxy, args.http_proxy_port), (make_socks_proxy, args.socks_proxy_port)]:
        proxy = factory(args.bind, port, state, (args.bind, args.port), credentials["Username"], credentials["Password"])
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
