from __future__ import annotations

import hashlib
import json
import os
import socket
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from app.config import AppConfig


JAVDB_SECRET = os.getenv(
    "JAVDB_SIGNATURE_SECRET",
    "71cf27bb3c0bcdf207b64abecddc970098c7421ee7203b9cdae54478478a199e7d5a6e1a57691123c1a931c057842fb73ba3b3c83bcd69c17ccf174081e3d8aa",
)

JAVDB_NODES = (
    {"id": "javdb-cn-1", "name": "国内1", "provider": "javdb", "url": "https://apidd.czssdgz.com"},
    {"id": "javdb-global", "name": "国外", "provider": "javdb", "url": "https://jdforrepam.com"},
    {"id": "javdb-cn-3", "name": "国内3", "provider": "javdb", "url": "https://apidd.spthgb.com"},
    {"id": "javdb-official", "name": "官方", "provider": "javdb", "url": "https://javdb.com"},
)


def build_javdb_signature(timestamp: int, secret: str = JAVDB_SECRET) -> str:
    digest = hashlib.md5(f"{timestamp}{secret}".encode("utf-8")).hexdigest()
    return f"{timestamp}.lpw6vgqzsp.{digest}"


class MetadataClient:
    def __init__(
        self,
        config: AppConfig,
        opener: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
    ):
        self.config = config
        self._opener = opener or urllib.request.urlopen
        self._clock = clock or time.time
        self._resolve_ip = socket.gethostbyname

    def search(self, query: str, limit: int = 1) -> dict[str, Any]:
        limit = max(1, min(int(limit), 60))
        if self.config.metadata_provider == "dbo":
            return self._search_dbo(query, limit)
        return self._search_javdb(query, limit)

    def _search_dbo(self, query: str, limit: int) -> dict[str, Any]:
        if not self.config.dbo_api_url or not self.config.dbo_api_key:
            raise RuntimeError("DBO 未配置")
        url = (
            f"{self.config.dbo_api_url.rstrip('/')}/api/search?"
            + urllib.parse.urlencode({"q": query, "limit": limit})
        )
        request = urllib.request.Request(url, headers={"X-API-Key": self.config.dbo_api_key})
        return self._read_json(request)

    def _search_javdb(self, query: str, limit: int) -> dict[str, Any]:
        selected = self.config.javdb_api_url.rstrip("/")
        urls = [selected] + [node["url"] for node in JAVDB_NODES if node["url"] != selected]
        last_error: Exception | None = None
        for base_url in urls:
            params = urllib.parse.urlencode({
                "q": query,
                "type": "movie",
                "movie_type": "all",
                "page": 1,
                "limit": limit,
            })
            request = urllib.request.Request(
                f"{base_url}/api/v2/search?{params}",
                headers=self._javdb_headers(),
            )
            try:
                payload = self._read_json(request)
                if payload.get("success") != 1:
                    raise RuntimeError(payload.get("message") or payload.get("action") or "JavDB API 请求失败")
                return payload
            except Exception as exc:
                last_error = exc
        raise RuntimeError(str(last_error or "所有 JavDB 节点均不可用"))

    def _javdb_headers(self) -> dict[str, str]:
        timestamp = int(self._clock())
        return {
            "User-Agent": "Dart/3.5 (dart:io)",
            "Accept-Language": "zh-TW",
            "jdSignature": build_javdb_signature(timestamp),
        }

    def _read_json(self, request: urllib.request.Request) -> dict[str, Any]:
        response = self._opener(request, timeout=10)
        return json.loads(response.read())

    def nodes(self) -> list[dict[str, Any]]:
        nodes = [dict(node) for node in JAVDB_NODES]
        nodes.append({
            "id": "dbo",
            "name": "DBO",
            "provider": "dbo",
            "url": self.config.dbo_api_url.rstrip("/"),
        })
        for node in nodes:
            node["current"] = (
                node["provider"] == self.config.metadata_provider
                and (node["provider"] == "dbo" or node["url"] == self.config.javdb_api_url.rstrip("/"))
            )
        return nodes

    def probe_nodes(self) -> list[dict[str, Any]]:
        node_ids = [node["id"] for node in self.nodes()]
        with ThreadPoolExecutor(max_workers=len(node_ids)) as executor:
            return list(executor.map(self.probe_node, node_ids))

    def probe_node(self, node_id: str) -> dict[str, Any]:
        node = next((item for item in self.nodes() if item["id"] == node_id), None)
        if node is None:
            raise KeyError(node_id)
        if node["provider"] == "dbo" and (not node["url"] or not self.config.dbo_api_key):
            return {**node, "ok": False, "ip": "-", "latency_ms": None, "error": "请先配置 DBO 地址和密钥"}
        try:
            host = urllib.parse.urlparse(node["url"]).hostname or ""
            ip = self._resolve_ip(host)
        except Exception:
            ip = "-"
        ok, latency_ms, error = self._measure(node)
        return {**node, "ok": ok, "ip": ip, "latency_ms": latency_ms, "error": error}

    def _measure(self, node: dict[str, Any]) -> tuple[bool, int | None, str]:
        started = time.perf_counter()
        try:
            if node["provider"] == "dbo":
                request = urllib.request.Request(
                    f"{node['url']}/api/search?q=test&limit=1",
                    headers={"X-API-Key": self.config.dbo_api_key},
                )
            else:
                params = urllib.parse.urlencode({
                    "q": "ping",
                    "type": "movie",
                    "movie_type": "all",
                    "page": 1,
                    "limit": 1,
                })
                request = urllib.request.Request(
                    f"{node['url']}/api/v2/search?{params}",
                    headers=self._javdb_headers(),
                )
            payload = self._read_json(request)
            if payload.get("success") not in (1, True):
                raise RuntimeError(payload.get("message") or "API 返回失败")
            latency = round((time.perf_counter() - started) * 1000)
            return True, latency, ""
        except Exception as exc:
            latency = round((time.perf_counter() - started) * 1000)
            return False, latency, str(exc)[:160]
