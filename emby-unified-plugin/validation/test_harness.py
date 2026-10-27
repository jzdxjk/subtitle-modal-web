import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


def harness():
    path = Path(__file__).with_name("emby_validation.py")
    if not path.exists():
        raise AssertionError("isolated Emby harness has not been implemented")
    if "emby_validation" not in sys.modules:
        spec = importlib.util.spec_from_file_location("emby_validation", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules["emby_validation"]


class HarnessBoundaryTests(unittest.TestCase):
    def owned_container(self, module):
        case = module.CASES["4.9.5.0"]
        root = module.ROOT / case.version
        return case, {
            "Name": "/" + case.container,
            "Config": {
                "Image": case.image,
                "Labels": {"codex.task": module.TASK},
            },
            "HostConfig": {
                "NanoCpus": 1_000_000_000,
                "Memory": 1_073_741_824,
                "PortBindings": {"8096/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(case.port)}]},
            },
            "Mounts": [
                {"Source": str(root / "config"), "Destination": "/config"},
                {"Source": str(root / "media"), "Destination": "/media"},
            ],
        }

    def test_rejects_versions_that_could_escape_the_test_directory(self):
        module = harness()
        with self.assertRaises(ValueError):
            module.case_for("../../emby")

    def test_refuses_production_or_unlabelled_containers(self):
        module = harness()
        case, info = self.owned_container(module)
        info["Name"] = "/emby"
        with self.assertRaises(RuntimeError):
            module.verify_container(case, info)
        info["Name"] = "/" + case.container
        info["Config"]["Labels"] = {}
        with self.assertRaises(RuntimeError):
            module.verify_container(case, info)

    def test_refuses_production_mounts_or_public_ports(self):
        module = harness()
        case, info = self.owned_container(module)
        info["Mounts"][0]["Source"] = "/volume1/docker/emby/config"
        with self.assertRaises(RuntimeError):
            module.verify_container(case, info)
        case, info = self.owned_container(module)
        info["HostConfig"]["PortBindings"]["8096/tcp"][0]["HostIp"] = "0.0.0.0"
        with self.assertRaises(RuntimeError):
            module.verify_container(case, info)

    def test_accepts_the_owned_resource_limited_container(self):
        module = harness()
        case, info = self.owned_container(module)
        module.verify_container(case, info)

    def test_http_failure_does_not_disclose_response_body_or_token(self):
        module = harness()
        client = module.EmbyClient(module.CASES["4.9.5.0"], token="private-test-token")
        failure = HTTPError(client.base + "/System/Info", 401, "Unauthorized", {}, io.BytesIO(b'private-test-token password-secret'))
        with patch("urllib.request.urlopen", side_effect=failure):
            with self.assertRaises(RuntimeError) as raised:
                client.request("GET", "/System/Info")
        self.assertNotIn("private-test-token", str(raised.exception))
        self.assertNotIn("password-secret", str(raised.exception))
        self.assertIn("401", str(raised.exception))

    def test_early_startup_connection_reset_is_a_retryable_sanitized_failure(self):
        module = harness()
        client = module.EmbyClient(module.CASES["4.8.11.0"])
        with patch("urllib.request.urlopen", side_effect=ConnectionResetError("startup reset")):
            try:
                client.request("GET", "/System/Info/Public")
            except Exception as error:
                self.assertIsInstance(error, RuntimeError)
                self.assertIn("isolated Emby", str(error))
            else:
                self.fail("startup reset was not reported")

    @unittest.skipIf(os.name == "nt", "POSIX permission acceptance runs on NAS")
    def test_private_session_file_is_owner_only(self):
        module = harness()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            module.write_private(path, {"AccessToken": "private-test-token"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["AccessToken"], "private-test-token")


if __name__ == "__main__":
    unittest.main()
