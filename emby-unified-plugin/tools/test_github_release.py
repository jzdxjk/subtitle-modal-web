import hashlib
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).with_name("github_release.py")


def module():
    if not SCRIPT.exists():
        raise AssertionError("GitHub release helper has not been implemented")
    spec = importlib.util.spec_from_file_location("github_release", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        status, data = self.responses.pop(0)
        return status, json.dumps(data).encode()


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.r = module()
        self.sha = "a" * 40
        self.dll = b"MZ synthetic test DLL bytes"
        self.version = "1.0.0.0"

    def asset(self, name, content, identity=1):
        return {"id": identity, "name": name, "state": "uploaded", "size": len(content),
                "digest": "sha256:" + hashlib.sha256(content).hexdigest()}

    def client(self, responses):
        fake = FakeTransport(responses)
        return self.r.GitHubClient(token="synthetic-test-token", transport=fake), fake

    def test_manifest_and_checksums_use_immutable_version_dll(self):
        files = self.r.release_files(self.dll, self.version)
        manifest = json.loads(files["update.json"])
        self.assertEqual(manifest["sha256"], hashlib.sha256(self.dll).hexdigest())
        self.assertEqual(manifest["plugin_id"], "76cd4168-e0b3-4aac-8a52-5cb638121744")
        self.assertEqual(manifest["channel"], "stable")
        self.assertEqual(manifest["minimum_server_versions"], {"4.8": "4.8.11.0", "4.9": "4.9.1.80", "4.10": "4.10.0.40"})
        self.assertIn("/emby-subtitle-assistant-v1.0.0.0/Emby.SubtitleAssistant.dll", manifest["download_url"])
        self.assertEqual(files["Emby.SubtitleAssistant.dll"], self.dll)
        self.assertIn(hashlib.sha256(files["update.json"]).hexdigest().encode(), files["SHA256SUMS.txt"])
        for bad in ["1.0", "1.0.0.0-rc1", "65536.0.0.0", "1.2.3.4/other"]:
            with self.assertRaises(self.r.ReleaseError):
                self.r.release_files(self.dll, bad)

    def test_unknown_hosts_paths_and_immutable_mutations_are_rejected(self):
        client, fake = self.client([])
        invalid = [("GET", "https://attacker.test/repos/jzdxjk/subtitle-modal-web"),
                   ("GET", "http://api.github.com/repos/jzdxjk/subtitle-modal-web"),
                   ("POST", "https://api.github.com/repos/other/repo/releases"),
                   ("POST", "https://api.github.com/repos/jzdxjk/subtitle-modal-web/issues"),
                   ("DELETE", "https://api.github.com/repos/jzdxjk/subtitle-modal-web/releases/assets/9"),
                   ("GET", "https://api.github.com/repos/jzdxjk/subtitle-modal-web/../other"),
                   ("GET", "https://api.github.com:444/repos/jzdxjk/subtitle-modal-web")]
        for method, url in invalid:
            with self.assertRaises(self.r.ReleaseError):
                client.request(method, url, operation="test")
        self.assertEqual(fake.calls, [])

    def test_redirect_is_rejected_without_following_or_leaking_token(self):
        client, fake = self.client([(302, {"url": "https://attacker.test"})])
        with self.assertRaisesRegex(self.r.ReleaseError, "HTTP 302") as error:
            client.request("GET", self.r.API + "/user", operation="auth")
        self.assertNotIn("synthetic-test-token", str(error.exception))
        self.assertEqual(len(fake.calls), 1)

    def test_401_can_retry_once_with_captured_gcm_token_only(self):
        fake = FakeTransport([(401, {"message": "synthetic-secret"}), (200, {"login": "jzdxjk"})])
        fallback = mock.Mock(return_value="synthetic-fallback-token")
        client = self.r.GitHubClient("synthetic-test-token", transport=fake, fallback=fallback)
        self.assertEqual(client.request("GET", self.r.API + "/user", operation="auth")["login"], "jzdxjk")
        fallback.assert_called_once()
        self.assertEqual(fake.calls[1][2]["Authorization"], "Bearer synthetic-fallback-token")

    def test_errors_do_not_expose_body_or_token(self):
        client, _ = self.client([(403, {"message": "synthetic-secret"})])
        with self.assertRaises(self.r.ReleaseError) as error:
            client.request("GET", self.r.API + "/user", operation="auth")
        self.assertEqual(str(error.exception), "GitHub HTTP 403 during auth.")

    def test_existing_immutable_asset_requires_same_digest(self):
        client, fake = self.client([])
        release = {"id": 10}
        assets = [self.asset("Emby.SubtitleAssistant.dll", b"different")]
        with self.assertRaisesRegex(self.r.ReleaseError, "immutable"):
            self.r.ensure_asset(client, release, assets, "Emby.SubtitleAssistant.dll", self.dll)
        self.assertEqual(fake.calls, [])
        existing = self.asset("Emby.SubtitleAssistant.dll", self.dll)
        self.assertEqual(self.r.ensure_asset(client, release, [existing], existing["name"], self.dll), existing)
        self.assertEqual(fake.calls, [])

    def test_legacy_asset_without_digest_is_refused_without_deleting(self):
        asset = self.asset("Emby.SubtitleAssistant.dll", self.dll)
        asset["digest"] = None
        client, fake = self.client([])
        with self.assertRaisesRegex(self.r.ReleaseError, "immutable"):
            self.r.ensure_asset(client, {"id": 10}, [asset], "Emby.SubtitleAssistant.dll", self.dll)
        self.assertEqual(fake.calls, [])

    def test_uploaded_asset_digest_is_checked(self):
        bad = self.asset("Emby.SubtitleAssistant.dll", b"changed")
        client, fake = self.client([(201, bad)])
        with self.assertRaisesRegex(self.r.ReleaseError, "digest"):
            self.r.ensure_asset(client, {"id": 10}, [], "Emby.SubtitleAssistant.dll", self.dll)
        self.assertEqual(fake.calls[0][0], "POST")
        self.assertTrue(fake.calls[0][1].startswith("https://uploads.github.com/repos/jzdxjk/subtitle-modal-web/releases/10/assets?name="))

    def test_pointer_uploads_before_old_delete_then_renames(self):
        manifest = self.r.release_files(self.dll, self.version)["update.json"]
        temporary = self.r.pointer_temporary_name(manifest)
        old = self.asset("update.json", b"old pointer", 21)
        uploaded = self.asset(temporary, manifest, 22)
        promoted = dict(uploaded, name="update.json")
        release = {"id": 20, "tag_name": self.r.POINTER_TAG, "draft": False}
        client, fake = self.client([(200, release), (200, [old]), (201, uploaded), (204, None), (200, promoted)])
        self.r.publish_pointer(client, manifest, self.sha)
        methods = [call[0] for call in fake.calls]
        self.assertEqual(methods, ["GET", "GET", "POST", "DELETE", "PATCH"])
        self.assertEqual(json.loads(fake.calls[-1][3]), {"name": "update.json", "label": "Stable update manifest"})
        self.assertNotIn("Emby.SubtitleAssistant.dll", fake.calls[2][1])

    def test_first_pointer_does_not_delete_the_newly_promoted_asset(self):
        manifest = self.r.release_files(self.dll, self.version)["update.json"]
        uploaded = self.asset(self.r.pointer_temporary_name(manifest), manifest, 22)
        release = {"id": 20, "tag_name": self.r.POINTER_TAG, "draft": False}
        client, fake = self.client([(200, release), (200, []), (201, uploaded), (200, dict(uploaded, name="update.json")), (204, None)])
        self.r.publish_pointer(client, manifest, self.sha)
        self.assertEqual([call[0] for call in fake.calls], ["GET", "GET", "POST", "PATCH"])

    def test_failed_pointer_upload_preserves_old_pointer(self):
        manifest = self.r.release_files(self.dll, self.version)["update.json"]
        release = {"id": 20, "tag_name": self.r.POINTER_TAG, "draft": False}
        client, fake = self.client([(200, release), (200, [self.asset("update.json", b"old", 21)]), (500, {"message": "must not echo"})])
        with self.assertRaisesRegex(self.r.ReleaseError, "HTTP 500"):
            self.r.publish_pointer(client, manifest, self.sha)
        self.assertEqual([call[0] for call in fake.calls], ["GET", "GET", "POST"])

    def test_pointer_promotion_can_resume_after_old_pointer_was_deleted(self):
        manifest = self.r.release_files(self.dll, self.version)["update.json"]
        release = {"id": 20, "tag_name": self.r.POINTER_TAG, "draft": False}
        temporary = self.asset(self.r.pointer_temporary_name(manifest), manifest, 22)
        client, fake = self.client([(200, release), (200, [temporary]), (200, dict(temporary, name="update.json"))])
        self.r.publish_pointer(client, manifest, self.sha)
        self.assertEqual([call[0] for call in fake.calls], ["GET", "GET", "PATCH"])

    def test_draft_release_uploads_all_files_before_publishing_and_pointer_update(self):
        files = self.r.release_files(self.dll, self.version)
        tag = "emby-subtitle-assistant-v" + self.version
        release = {"id": 10, "tag_name": tag, "draft": True, "prerelease": False, "target_commitish": self.sha}
        pointer = {"id": 20, "tag_name": self.r.POINTER_TAG, "draft": False}
        uploaded = self.asset(self.r.pointer_temporary_name(files["update.json"]), files["update.json"], 22)
        responses = [(404, None), (404, None), (201, release), (200, [])]
        responses += [(201, self.asset(name, content, index)) for index, (name, content) in enumerate(files.items(), 11)]
        responses += [(200, dict(release, draft=False)), (404, None), (201, pointer), (200, []), (201, uploaded), (200, dict(uploaded, name="update.json")), (204, None)]
        client, fake = self.client(responses)
        self.assertEqual(self.r.publish(client, self.dll, self.version, self.sha, "Concrete release notes"),
                         "https://github.com/jzdxjk/subtitle-modal-web/releases/tag/" + tag)
        mutations = [(method, url, body) for method, url, _, body in fake.calls if method != "GET"]
        self.assertEqual([item[0] for item in mutations], ["POST", "POST", "POST", "POST", "PATCH", "POST", "POST", "PATCH"])
        creation = json.loads(mutations[0][2])
        self.assertTrue(creation["draft"])
        self.assertFalse(creation["prerelease"])
        self.assertEqual(creation["make_latest"], "false")
        self.assertEqual(creation["target_commitish"], self.sha)
        self.assertEqual(json.loads(mutations[4][2])["make_latest"], "false")

    def test_same_existing_release_and_pointer_need_no_mutations(self):
        files = self.r.release_files(self.dll, self.version)
        release = {"id": 10, "tag_name": "emby-subtitle-assistant-v" + self.version, "draft": False}
        pointer = {"id": 20, "tag_name": self.r.POINTER_TAG, "draft": False}
        assets = [self.asset(name, content, index) for index, (name, content) in enumerate(files.items(), 11)]
        client, fake = self.client([(200, release), (200, {"object": {"type": "commit", "sha": self.sha}}),
                                    (200, assets), (200, pointer), (200, [self.asset("update.json", files["update.json"], 21)])])
        self.r.publish(client, self.dll, self.version, self.sha, "notes")
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))

    def test_existing_release_tag_sha_mismatch_stops_before_mutations(self):
        release = {"id": 10, "tag_name": "emby-subtitle-assistant-v1.0.0.0", "draft": False}
        client, fake = self.client([(200, release), (200, {"object": {"type": "commit", "sha": "b" * 40}})])
        with self.assertRaisesRegex(self.r.ReleaseError, "commit"):
            self.r.publish(client, self.dll, self.version, self.sha, "Release notes")
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))

    def test_public_check_never_reads_credentials(self):
        fake = FakeTransport([(200, {"full_name": "jzdxjk/subtitle-modal-web"})])
        with mock.patch.object(self.r, "load_token", side_effect=AssertionError("must stay public")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.r.main(["--check-public"], transport=fake), 0)
        self.assertNotIn("Authorization", fake.calls[0][2])

    def test_publish_cli_reads_real_temp_dll_and_body_files_before_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            dll = Path(directory) / "Emby.SubtitleAssistant.dll"
            body = Path(directory) / "release.md"
            dll.write_bytes(self.dll)
            body.write_text("Concrete notes 中文\nSecond line", encoding="utf-8")
            with mock.patch.object(self.r, "load_token", return_value="synthetic-test-token"), \
                 mock.patch.object(self.r, "publish", return_value="https://github.com/jzdxjk/subtitle-modal-web/releases/tag/test") as publish, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.r.main(["--publish", "--dll", str(dll), "--version", self.version,
                                              "--commit", self.sha, "--body-file", str(body)], transport=FakeTransport([])), 0)
            self.assertEqual(publish.call_args.args[1:], (self.dll, self.version, self.sha, "Concrete notes 中文\nSecond line"))

    def test_credentials_are_captured_without_echo_and_git_never_prompts(self):
        completed = mock.Mock(returncode=0, stdout="synthetic-gh-token\n", stderr="must never echo")
        with mock.patch.dict(os.environ, {"GH_TOKEN": ""}), mock.patch.object(self.r.subprocess, "run", return_value=completed) as run:
            self.assertEqual(self.r.load_token(), "synthetic-gh-token")
            self.assertEqual(run.call_args.args[0], ["gh", "auth", "token", "--hostname", "github.com"])
        completed.stdout = "protocol=https\nhost=github.com\nusername=jzdxjk\npassword=synthetic-gcm-token\n\n"
        with mock.patch.object(self.r.subprocess, "run", return_value=completed) as run:
            self.assertEqual(self.r.load_gcm_token(), "synthetic-gcm-token")
            self.assertEqual(run.call_args.kwargs["input"], "protocol=https\nhost=github.com\n\n")
            self.assertEqual(run.call_args.kwargs["env"]["GCM_INTERACTIVE"], "never")
            self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            command = run.call_args.args[0]
            self.assertIn("credential.helper=", command)
            self.assertIn("credential.helper=manager", command)

    def test_api_connection_preserves_uppercase_sni_and_verified_context(self):
        connection = self.r.GitHubAPIConnection("api.github.com", timeout=9, context=self.r.verified_context())
        wrapped = mock.Mock()
        context = mock.Mock()
        context.wrap_socket.return_value = wrapped
        raw = mock.Mock()
        with mock.patch.object(self.r, "resolve_api_addresses", return_value=("20.205.243.168",)), \
             mock.patch.object(self.r.socket, "create_connection", return_value=raw) as connect, \
             mock.patch.object(connection, "_context", context):
            connection.connect()
        connect.assert_called_once_with(("20.205.243.168", 443), timeout=9)
        context.wrap_socket.assert_called_once_with(raw, server_hostname="API.GITHUB.COM")
        self.assertIs(connection.sock, wrapped)

    def test_verified_context_never_disables_certificate_checks(self):
        context = self.r.verified_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        with mock.patch.object(self.r.ssl, "create_default_context", return_value=ssl._create_unverified_context()):
            with self.assertRaises(self.r.ReleaseError):
                self.r.verified_context()

    def test_doh_filters_fake_private_ips_and_caches_public_api_answers(self):
        calls = []
        def query(url):
            calls.append(url)
            return {"Status": 0, "Answer": [{"type": 1, "data": "198.18.0.61"}, {"type": 1, "data": "20.205.243.168"}]}
        self.assertEqual(self.r.resolve_api_addresses(query), ("20.205.243.168",))
        self.assertEqual(self.r.resolve_api_addresses(query), ("20.205.243.168",))
        self.assertEqual(len(calls), 1)

    def test_draft_pr_reuses_existing_and_posts_structured_json(self):
        url = "https://github.com/jzdxjk/subtitle-modal-web/pull/7"
        client, fake = self.client([(200, [{"html_url": url}])])
        self.assertEqual(self.r.create_pr(client, "codex/subtitle-assistant", "dev", "Chinese 中文\nbody"), url)
        self.assertEqual(len(fake.calls), 1)
        client, fake = self.client([(200, []), (201, {"html_url": url})])
        self.assertEqual(self.r.create_pr(client, "codex/subtitle-assistant", "dev", "Chinese 中文\nbody"), url)
        payload = json.loads(fake.calls[-1][3])
        self.assertTrue(payload["draft"])
        self.assertEqual(payload["body"], "Chinese 中文\nbody")
        self.assertEqual(payload["base"], "dev")


if __name__ == "__main__":
    unittest.main()
