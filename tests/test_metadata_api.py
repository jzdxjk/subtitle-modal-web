import hashlib
import json
from types import SimpleNamespace

import pytest

from app.config import AppConfig
from app.metadata_api import JAVDB_NODES, MetadataClient, build_javdb_signature


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = headers or {"Content-Type": "application/json"}

    def read(self):
        return self.payload


def test_javdb_signature_uses_timestamp_and_fixed_secret():
    secret = "secret"

    signature = build_javdb_signature(1722510000, secret)

    digest = hashlib.md5(b"1722510000secret").hexdigest()
    assert signature == f"1722510000.lpw6vgqzsp.{digest}"


def test_javdb_search_signs_request_and_falls_back_to_next_mirror():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        if len(requests) == 1:
            raise OSError("primary unavailable")
        return FakeResponse({"success": 1, "data": {"movies": [{"number": "FNS-192"}]}})

    config = AppConfig(metadata_provider="javdb", javdb_api_url=JAVDB_NODES[0]["url"])
    client = MetadataClient(config, opener=opener, clock=lambda: 1722510000)

    result = client.search("FNS-192", 1)

    assert result["data"]["movies"][0]["number"] == "FNS-192"
    assert len(requests) == 2
    assert requests[0].get_header("Jdsignature").startswith("1722510000.lpw6vgqzsp.")
    assert "type=movie" in requests[0].full_url
    assert "q=FNS-192" in requests[0].full_url


def test_javdb_search_rejects_http_200_api_failure():
    client = MetadataClient(
        AppConfig(metadata_provider="javdb"),
        opener=lambda request, timeout: FakeResponse({"success": 0, "message": "ParameterInvalid"}),
    )

    with pytest.raises(RuntimeError, match="ParameterInvalid"):
        client.search("FNS-192", 1)


def test_dbo_search_uses_custom_url_and_api_key_without_provider_fallback():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return FakeResponse({"success": 1, "data": {"movies": []}})

    config = AppConfig(metadata_provider="dbo", dbo_api_url="https://dbo.example.com", dbo_api_key="key-1")

    result = MetadataClient(config, opener=opener).search("FNS-192", 3)

    assert result["success"] == 1
    assert requests[0].full_url == "https://dbo.example.com/api/search?q=FNS-192&limit=3"
    assert requests[0].get_header("X-api-key") == "key-1"


def test_node_listing_contains_four_javdb_nodes_and_custom_dbo():
    config = AppConfig(
        metadata_provider="dbo",
        dbo_api_url="https://dbo.example.com",
        dbo_api_key="secret",
    )
    client = MetadataClient(config, opener=lambda request, timeout: FakeResponse({"success": 1, "data": {}}))
    client._resolve_ip = lambda host: "198.18.0.1"
    client._measure = lambda node: (True, 274, "")

    nodes = client.probe_nodes()

    assert len(nodes) == 5
    assert sum(node["provider"] == "javdb" for node in nodes) == 4
    assert nodes[-1]["provider"] == "dbo"
    assert nodes[-1]["url"] == "https://dbo.example.com"
    assert nodes[-1]["current"] is True
    assert all(node["ip"] == "198.18.0.1" for node in nodes)


def test_unconfigured_dbo_node_is_reported_without_network_request():
    client = MetadataClient(AppConfig(), opener=lambda request, timeout: pytest.fail("network called"))

    dbo = client.probe_node("dbo")

    assert dbo["ok"] is False
    assert dbo["error"] == "请先配置 DBO 地址和密钥"
    assert dbo["latency_ms"] is None


def test_javdb_probe_uses_working_search_endpoint():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return FakeResponse({"success": 1, "data": {"movies": []}})

    client = MetadataClient(AppConfig(metadata_provider="javdb"), opener=opener)
    client._resolve_ip = lambda host: "198.18.0.1"

    result = client.probe_node("javdb-global")

    assert result["ok"] is True
    assert "/api/v2/search?" in requests[0].full_url
    assert "q=ping" in requests[0].full_url
