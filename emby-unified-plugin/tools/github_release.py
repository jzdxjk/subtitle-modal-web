#!/usr/bin/env python3
"""Repository-specific GitHub release helper. No credentials are read by --check-public."""
import argparse
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
from urllib.parse import parse_qs, urlencode, urlsplit

REPOSITORY = "jzdxjk/subtitle-modal-web"
API = "https://api.github.com"
ROOT = "/repos/" + REPOSITORY
POINTER_TAG = "emby-subtitle-assistant-update"
DLL_NAME = "Emby.SubtitleAssistant.dll"
TAG_PREFIX = "emby-subtitle-assistant-v"
_API_ADDRESSES = None


class ReleaseError(Exception):
    """Only sanitized, operator-facing messages belong here."""


def verified_context():
    context = ssl.create_default_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise ReleaseError("TLS certificate verification must remain enabled.")
    return context


def _read_limited(response, maximum=16 * 1024 * 1024):
    body = response.read(maximum + 1)
    if len(body) > maximum:
        raise ReleaseError("GitHub response exceeded the allowed size.")
    return body


def _doh_query(url):
    # Never receives, reads, or sends a GitHub credential.
    target = urlsplit(url)
    connection = http.client.HTTPSConnection(target.hostname, timeout=15, context=verified_context())
    try:
        connection.request("GET", target.path + "?" + target.query,
                           headers={"Accept": "application/dns-json", "User-Agent": "SubtitleAssistantRelease/1"})
        response = connection.getresponse()
        if response.status != 200:
            raise ReleaseError("Public HTTPS DNS lookup failed.")
        return json.loads(_read_limited(response, 65536))
    finally:
        connection.close()


def resolve_api_addresses(query=None):
    global _API_ADDRESSES
    if _API_ADDRESSES is not None:
        return _API_ADDRESSES
    query = query or _doh_query
    for url in ("https://1.1.1.1/dns-query?name=api.github.com&type=A",
                "https://dns.google/resolve?name=api.github.com&type=A"):
        try:
            result = query(url)
            addresses = []
            if result.get("Status") != 0:
                continue
            for answer in result.get("Answer", []):
                if answer.get("type") != 1:
                    continue
                address = ipaddress.ip_address(answer.get("data", ""))
                if address.version == 4 and address.is_global and str(address) not in addresses:
                    addresses.append(str(address))
            if addresses:
                _API_ADDRESSES = tuple(addresses)
                return _API_ADDRESSES
        except (OSError, ValueError, ReleaseError, http.client.HTTPException):
            continue
    raise ReleaseError("No public GitHub API IPv4 address was returned by verified HTTPS DNS.")


class GitHubAPIConnection(http.client.HTTPSConnection):
    def connect(self):
        # Work around this network's case-sensitive SNI/fake-IP failure without changing OS DNS.
        for address in resolve_api_addresses():
            raw = None
            try:
                raw = socket.create_connection((address, 443), timeout=self.timeout)
                self.sock = self._context.wrap_socket(raw, server_hostname="API.GITHUB.COM")
                return
            except (OSError, ssl.SSLError):
                if raw is not None:
                    raw.close()
        raise ReleaseError("Verified GitHub API TLS connection failed.")


def network_transport(method, url, headers, body):
    target = urlsplit(url)
    if target.scheme != "https" or target.hostname not in ("api.github.com", "uploads.github.com"):
        raise ReleaseError("GitHub transport host is not allowed.")
    context = verified_context()
    cls = GitHubAPIConnection if target.hostname == "api.github.com" else http.client.HTTPSConnection
    connection = cls(target.hostname, timeout=90, context=context)
    try:
        path = target.path + ("?" + target.query if target.query else "")
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        # http.client never follows redirects; credentials stay on the original GitHub host.
        return response.status, _read_limited(response)
    finally:
        connection.close()


def _token(value):
    value = (value or "").strip()
    if not value or any(ord(character) <= 32 or ord(character) == 127 for character in value):
        raise ReleaseError("No usable existing GitHub credential was found.")
    return value


def load_token():
    if os.environ.get("GH_TOKEN"):
        return _token(os.environ["GH_TOKEN"])
    try:
        result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=20, check=False)
        if result.returncode == 0:
            return _token(result.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    raise ReleaseError("No usable existing GitHub credential was found; no login was changed.")


def load_gcm_token():
    # Called only after an actual GitHub HTTP 401. Never log captured stdout/stderr.
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GCM_GUI_PROMPT="0")
    try:
        result = subprocess.run(["git", "-c", "credential.helper=", "-c", "credential.helper=manager",
                                 "-c", "credential.interactive=never", "-c", "credential.guiPrompt=false",
                                 "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
                                timeout=20, check=False)
        if result.returncode == 0:
            fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            if fields.get("host", "github.com") == "github.com" and fields.get("protocol", "https") == "https":
                return _token(fields.get("password"))
    except (OSError, subprocess.SubprocessError, ReleaseError):
        pass
    return None


def _identity(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d*", str(value)):
        raise ReleaseError("GitHub returned an invalid numeric identity.")
    return str(value)


def _tag(value):
    return value == POINTER_TAG or re.fullmatch(re.escape(TAG_PREFIX) + r"\d+\.\d+\.\d+\.\d+", value) is not None


class GitHubClient:
    def __init__(self, token=None, transport=None, fallback=None):
        self.token = _token(token) if token is not None else None
        self.transport = transport or network_transport
        self.fallback = fallback
        self.fallback_attempted = False
        self.upload_release_ids = set()
        self.draft_release_ids = set()
        self.mutable_asset_ids = set()

    def _allow(self, method, url):
        target = urlsplit(url)
        if (target.scheme != "https" or target.hostname not in ("api.github.com", "uploads.github.com")
                or target.username is not None or target.password is not None or target.port not in (None, 443)
                or target.fragment or "%" in target.path or ".." in target.path or "\\" in target.path):
            raise ReleaseError("GitHub request host or path is not allowed.")
        path = target.path
        query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True) if target.query else {}
        allowed = False
        if target.hostname == "uploads.github.com":
            match = re.fullmatch(re.escape(ROOT) + r"/releases/([1-9]\d*)/assets", path)
            allowed = method == "POST" and match is not None and match[1] in self.upload_release_ids and set(query) == {"name"} and len(query["name"]) == 1
            if allowed:
                name = query["name"][0]
                allowed = name in (DLL_NAME, "update.json", "SHA256SUMS.txt") or re.fullmatch(r"update\.pending-[0-9a-f]{64}\.json", name) is not None
        elif method == "GET":
            allowed = not query and path in (ROOT, "/user", "/rate_limit")
            for suffix in ("/releases/tags/", "/git/ref/tags/"):
                if path.startswith(ROOT + suffix) and not query and _tag(path[len(ROOT + suffix):]):
                    allowed = True
            if not query and re.fullmatch(re.escape(ROOT) + r"/git/tags/[0-9a-f]{40}", path):
                allowed = True
            if re.fullmatch(re.escape(ROOT) + r"/releases/[1-9]\d*/assets", path):
                allowed = set(query) <= {"page", "per_page"} and all(len(values) == 1 and values[0].isdigit() for values in query.values())
            if path == ROOT + "/pulls":
                allowed = query == {"state": ["open"], "head": ["jzdxjk:codex/subtitle-assistant"], "base": ["dev"], "per_page": ["100"]}
        elif method == "POST":
            allowed = not query and path in (ROOT + "/releases", ROOT + "/pulls")
        elif method in ("PATCH", "DELETE") and not query:
            match = re.fullmatch(re.escape(ROOT) + r"/releases/assets/([1-9]\d*)", path)
            allowed = match is not None and match[1] in self.mutable_asset_ids
            draft = re.fullmatch(re.escape(ROOT) + r"/releases/([1-9]\d*)", path)
            if method == "PATCH" and draft is not None and draft[1] in self.draft_release_ids:
                allowed = True
        if not allowed:
            raise ReleaseError("GitHub request method or endpoint is not allowed.")

    def request(self, method, url, *, operation, data=None, content=None, optional=False):
        try:
            self._allow(method, url)
        except (ValueError, TypeError):
            raise ReleaseError("GitHub request host or path is not allowed.") from None
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "SubtitleAssistantRelease/1",
                   "X-GitHub-Api-Version": "2026-03-10"}
        if content is not None:
            body = content
            headers["Content-Type"] = "application/octet-stream"
        elif data is not None:
            body = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            body = None
        for attempt in range(2):
            if self.token is not None:
                headers["Authorization"] = "Bearer " + self.token
            try:
                status, response = self.transport(method, url, headers, body)
            except ReleaseError:
                raise
            except (OSError, ValueError, http.client.HTTPException):
                raise ReleaseError("GitHub transport failed during " + operation + ".") from None
            if status == 401 and not attempt and self.token is not None and self.fallback and not self.fallback_attempted:
                self.fallback_attempted = True
                replacement = self.fallback()
                if replacement and replacement != self.token:
                    self.token = _token(replacement)
                    headers = dict(headers)
                    continue
            if status == 404 and optional:
                return None
            if status not in (200, 201, 204):
                raise ReleaseError("GitHub HTTP " + str(status) + " during " + operation + ".")
            if status == 204:
                return None
            try:
                return json.loads(response)
            except (ValueError, TypeError):
                raise ReleaseError("Invalid GitHub JSON during " + operation + ".") from None


def validate_version(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version) or any(int(x) > 65535 for x in version.split(".")):
        raise ReleaseError("Version must be a four-part stable assembly version.")
    if ".".join(str(int(x)) for x in version.split(".")) != version:
        raise ReleaseError("Version components must use canonical decimal spelling.")


def release_files(dll, version):
    validate_version(version)
    if not dll or len(dll) > 64 * 1024 * 1024:
        raise ReleaseError("DLL must contain between 1 byte and 64 MiB.")
    digest = hashlib.sha256(dll).hexdigest()
    manifest = {"version": version,
                "download_url": "https://github.com/" + REPOSITORY + "/releases/download/" + TAG_PREFIX + version + "/" + DLL_NAME,
                "sha256": digest, "plugin_id": "76cd4168-e0b3-4aac-8a52-5cb638121744", "channel": "stable",
                "minimum_server_versions": {"4.8": "4.8.11.0", "4.9": "4.9.1.80", "4.10": "4.10.0.40"}}
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    checksums = digest + "  " + DLL_NAME + "\n" + hashlib.sha256(manifest_bytes).hexdigest() + "  update.json\n"
    return {DLL_NAME: dll, "update.json": manifest_bytes, "SHA256SUMS.txt": checksums.encode("ascii")}


def list_assets(client, release):
    assets = []
    for page in range(1, 101):
        batch = client.request("GET", API + ROOT + "/releases/" + _identity(release["id"]) + "/assets?per_page=100&page=" + str(page), operation="list release assets")
        if not isinstance(batch, list):
            raise ReleaseError("Invalid GitHub asset list.")
        assets.extend(batch)
        if len(batch) < 100:
            return assets
    raise ReleaseError("GitHub asset list exceeded the allowed pages.")


def _matching_asset(assets, name, content):
    matches = [asset for asset in assets if asset.get("name") == name]
    if len(matches) > 1:
        raise ReleaseError("Duplicate immutable asset names were returned.")
    if not matches:
        return None
    asset = matches[0]
    digest = asset.get("digest")
    if (not isinstance(digest, str) or digest.lower() != "sha256:" + hashlib.sha256(content).hexdigest()
            or asset.get("size") != len(content) or asset.get("state") != "uploaded"):
        raise ReleaseError("Existing immutable asset digest differs or cannot be verified; replacement refused.")
    return asset


def ensure_asset(client, release, assets, name, content):
    existing = _matching_asset(assets, name, content)
    if existing is not None:
        return existing
    release_id = _identity(release["id"])
    client.upload_release_ids.add(release_id)
    asset = client.request("POST", "https://uploads.github.com" + ROOT + "/releases/" + release_id + "/assets?" + urlencode({"name": name}),
                           operation="upload release asset", content=content)
    _matching_asset([asset], name, content)
    if asset.get("name") != name:
        raise ReleaseError("Uploaded asset name or digest did not match.")
    assets.append(asset)
    return asset


def pointer_temporary_name(manifest):
    return "update.pending-" + hashlib.sha256(manifest).hexdigest() + ".json"


def publish_pointer(client, manifest, commit):
    release = client.request("GET", API + ROOT + "/releases/tags/" + POINTER_TAG, operation="read update pointer release", optional=True)
    if release is None:
        release = client.request("POST", API + ROOT + "/releases", operation="create update pointer release", data={
            "tag_name": POINTER_TAG, "target_commitish": commit, "name": "Subtitle Assistant stable update metadata",
            "body": "Update manifest only; DLLs remain on immutable version releases.", "draft": False, "prerelease": False, "make_latest": "false"})
    if release.get("tag_name") != POINTER_TAG or release.get("draft") or release.get("immutable"):
        raise ReleaseError("Update pointer release is not a mutable published metadata release.")
    assets = list_assets(client, release)
    for asset in assets:
        if asset.get("name") != "update.json" and not re.fullmatch(r"update\.pending-[0-9a-f]{64}\.json", asset.get("name", "")):
            raise ReleaseError("Unexpected asset exists on the metadata-only pointer release.")
        client.mutable_asset_ids.add(_identity(asset["id"]))
    old = [asset for asset in assets if asset.get("name") == "update.json"]
    if len(old) > 1:
        raise ReleaseError("Duplicate update pointer names were returned.")
    if old and (old[0].get("digest") or "").lower() == "sha256:" + hashlib.sha256(manifest).hexdigest():
        _matching_asset(old, "update.json", manifest)
        active_id = _identity(old[0]["id"])
    else:
        temporary = ensure_asset(client, release, assets, pointer_temporary_name(manifest), manifest)
        client.mutable_asset_ids.add(_identity(temporary["id"]))
        for asset in old:
            client.request("DELETE", API + ROOT + "/releases/assets/" + _identity(asset["id"]), operation="remove old update pointer")
        promoted = client.request("PATCH", API + ROOT + "/releases/assets/" + _identity(temporary["id"]), operation="promote verified update pointer",
                                  data={"name": "update.json", "label": "Stable update manifest"})
        _matching_asset([promoted], "update.json", manifest)
        if promoted.get("name") != "update.json":
            raise ReleaseError("Update pointer promotion could not be verified.")
        active_id = _identity(promoted["id"])
        if active_id != _identity(temporary["id"]):
            raise ReleaseError("Update pointer promotion identity did not match.")
    # Only this helper's disposable staging assets may be cleaned up, never version-release assets.
    for asset in assets:
        if asset.get("name", "").startswith("update.pending-") and _identity(asset["id"]) != active_id:
            client.request("DELETE", API + ROOT + "/releases/assets/" + _identity(asset["id"]), operation="remove stale update staging asset")


def _verify_tag_commit(client, tag, commit, draft=None):
    ref = client.request("GET", API + ROOT + "/git/ref/tags/" + tag, operation="verify release tag commit", optional=True)
    if ref is None:
        if draft is not None and draft.get("draft") and draft.get("target_commitish") == commit:
            return
        if draft is None:
            return  # A new release may create this absent tag at the supplied exact SHA.
        raise ReleaseError("Published release tag commit could not be verified.")
    obj = ref.get("object", {})
    for _ in range(5):
        if obj.get("type") != "tag":
            break
        sha = obj.get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ReleaseError("Invalid annotated release tag commit.")
        obj = client.request("GET", API + ROOT + "/git/tags/" + sha, operation="verify annotated release tag").get("object", {})
    if obj.get("type") != "commit" or obj.get("sha") != commit:
        raise ReleaseError("Existing release tag points to a different commit; publication refused.")


def publish(client, dll, version, commit, body):
    files = release_files(dll, version)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReleaseError("Commit must be the exact lowercase 40-character GitHub SHA.")
    tag = TAG_PREFIX + version
    release = client.request("GET", API + ROOT + "/releases/tags/" + tag, operation="read version release", optional=True)
    _verify_tag_commit(client, tag, commit, draft=release)
    if release is None:
        release = client.request("POST", API + ROOT + "/releases", operation="create draft version release", data={
            "tag_name": tag, "target_commitish": commit, "name": "Subtitle Assistant " + version,
            "body": body, "draft": True, "prerelease": False, "make_latest": "false"})
    if release.get("tag_name") != tag or release.get("prerelease"):
        raise ReleaseError("Existing version release is not the requested stable tag.")
    assets = list_assets(client, release)
    for name, content in files.items():
        _matching_asset(assets, name, content)  # Check every conflict before uploading anything.
    for name, content in files.items():
        ensure_asset(client, release, assets, name, content)
    if release.get("draft"):
        release_id = _identity(release["id"])
        client.draft_release_ids.add(release_id)
        release = client.request("PATCH", API + ROOT + "/releases/" + release_id, operation="publish verified version release",
                                 data={"draft": False, "prerelease": False, "make_latest": "false"})
        if release.get("draft") or release.get("tag_name") != tag:
            raise ReleaseError("Published version release could not be verified.")
    publish_pointer(client, files["update.json"], commit)
    return "https://github.com/" + REPOSITORY + "/releases/tag/" + tag


def create_pr(client, head, base, body):
    if head != "codex/subtitle-assistant" or base != "dev":
        raise ReleaseError("This helper only creates codex/subtitle-assistant into dev.")
    query = urlencode({"state": "open", "head": "jzdxjk:" + head, "base": base, "per_page": 100})
    existing = client.request("GET", API + ROOT + "/pulls?" + query, operation="find existing pull request")
    if not isinstance(existing, list) or len(existing) > 1:
        raise ReleaseError("Existing pull request could not be selected safely.")
    result = existing[0] if existing else client.request("POST", API + ROOT + "/pulls", operation="create draft pull request", data={
        "title": "Merge Emby subtitle plugins into Subtitle Assistant", "head": head, "base": base, "body": body, "draft": True})
    url = result.get("html_url", "")
    if not re.fullmatch(r"https://github\.com/" + re.escape(REPOSITORY) + r"/pull/[1-9]\d*", url):
        raise ReleaseError("GitHub returned an unexpected pull request URL.")
    return url


def main(argv=None, *, transport=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("check-public", "check-auth", "publish", "create-pr"):
        modes.add_argument("--" + mode, action="store_true")
    parser.add_argument("--dll", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--commit")
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--head", default="codex/subtitle-assistant")
    parser.add_argument("--base", default="dev")
    args = parser.parse_args(argv)
    try:
        if args.check_public:
            result = GitHubClient(transport=transport).request("GET", API + ROOT, operation="public repository check")
            if result.get("full_name") != REPOSITORY:
                raise ReleaseError("Public repository identity did not match.")
            print("Public repository reachable: " + REPOSITORY + " (verified HTTPS).")
            return 0
        if args.publish and not all((args.dll, args.version, args.commit, args.body_file)):
            raise ReleaseError("--publish requires --dll, --version, --commit and --body-file.")
        if args.create_pr and not args.body_file:
            raise ReleaseError("--create-pr requires --body-file.")
        # Validate local input before any credential is fetched or remote mutation is attempted.
        body = args.body_file.read_text(encoding="utf-8-sig") if args.body_file else ""
        dll = None
        if args.publish:
            if args.dll.name != DLL_NAME:
                raise ReleaseError("DLL filename must be " + DLL_NAME + ".")
            dll = args.dll.read_bytes()
            release_files(dll, args.version)
            if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
                raise ReleaseError("Commit must be the exact lowercase 40-character GitHub SHA.")
        client = GitHubClient(load_token(), transport=transport, fallback=load_gcm_token)
        if args.check_auth:
            result = client.request("GET", API + "/user", operation="authentication check")
            login = result.get("login", "")
            if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
                raise ReleaseError("GitHub authenticated identity could not be verified.")
            print("Authenticated GitHub account: " + login)
        elif args.publish:
            print(publish(client, dll, args.version, args.commit, body))
        elif args.create_pr:
            print(create_pr(client, args.head, args.base, body))
        return 0
    except ReleaseError as error:
        print(str(error), file=sys.stderr)
    except Exception:
        # OS, subprocess and backend exceptions may include sensitive values. Do not print them.
        print("GitHub release operation failed; no backend response or credential is displayed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
