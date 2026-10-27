#!/usr/bin/env python3
"""Owned, resource-limited Emby hosts. Run on NAS through nas-sudo.ps1."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request


TASK = "subtitle-assistant-validation-20261027"
ROOT = Path("/volume1/docker/emby-subtitle-assistant-validation-20261027")
LIBRARY_NAME = "Codex Subtitle Assistant Validation"


@dataclass(frozen=True)
class Case:
    version: str
    suffix: str
    port: int

    @property
    def container(self):
        return "codex-subtitle-assistant-" + self.suffix

    @property
    def image(self):
        return "emby/embyserver:" + self.version


CASES = {case.version: case for case in [
    Case("4.8.11.0", "4811", 19048),
    Case("4.9.1.80", "49180", 19049),
    Case("4.9.5.0", "495", 19059),
    Case("4.10.0.40", "410040", 19040),
    Case("4.10.2.0", "4102", 19042),
]}


def case_for(version):
    if version not in CASES:
        raise ValueError("version is outside the five authorized official versions")
    return CASES[version]


def ensure_root():
    marker = ROOT / "task-marker.txt"
    if not ROOT.exists():
        ROOT.mkdir(mode=0o700)
        marker.write_text("task=" + TASK + "\nowner=codex-subtitle-assistant\n")
        marker.chmod(0o600)
    if not marker.is_file() or marker.read_text().splitlines()[0] != "task=" + TASK:
        raise RuntimeError("existing validation root is not marked for this task")
    for name in ["scripts", "reports", "images"]:
        (ROOT / name).mkdir(mode=0o700, exist_ok=True)


def docker(*args, missing_ok=False):
    result = subprocess.run(["docker", *args], text=True, capture_output=True)
    if result.returncode:
        if missing_ok:
            return None
        raise RuntimeError("docker " + args[0] + " failed: " + result.stderr.strip())
    return result.stdout.strip()


def inspect(case):
    raw = docker("inspect", case.container, missing_ok=True)
    return json.loads(raw)[0] if raw else None


def verify_container(case, info):
    expected_mounts = {
        (str(ROOT / case.version / "config"), "/config"),
        (str(ROOT / case.version / "media"), "/media"),
    }
    config = info.get("Config", {})
    host = info.get("HostConfig", {})
    bindings = {"8096/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(case.port)}]}
    actual_mounts = {(item.get("Source"), item.get("Destination")) for item in info.get("Mounts", [])}
    if (info.get("Name") != "/" + case.container
            or config.get("Labels", {}).get("codex.task") != TASK
            or config.get("Image") != case.image
            or actual_mounts != expected_mounts
            or host.get("NanoCpus") != 1_000_000_000
            or host.get("Memory") != 1_073_741_824
            or host.get("PortBindings") != bindings):
        raise RuntimeError("container ownership, mounts, limits or loopback ports do not match the validation case")


def write_private(path, value):
    temporary = path.with_name(path.name + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    path.chmod(0o600)


class EmbyClient:
    def __init__(self, case, token=None):
        self.case = case
        self.base = "http://127.0.0.1:" + str(case.port) + "/emby"
        self.token = token
        self.last_status = None

    def request(self, method, path, payload=None):
        self.last_status = None
        if not path.startswith("/") or "://" in path:
            raise ValueError("API path must stay on the isolated loopback host")
        headers = {
            "Accept": "application/json",
            "X-Emby-Authorization": 'Emby Client="CodexValidation", Device="IsolatedNAS", DeviceId="'
                + self.case.container + '", Version="1.0"',
        }
        if self.token:
            headers["X-Emby-Token"] = self.token
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                self.last_status = response.status
                body = response.read()
                if not body:
                    return None
                if "json" in response.headers.get("Content-Type", ""):
                    return json.loads(body)
                return body.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            # Error bodies can contain auth responses; neither body nor headers are logged.
            raise RuntimeError(method + " " + path.split("?")[0] + " returned HTTP " + str(error.code)) from None
        except OSError:
            raise RuntimeError(method + " " + path.split("?")[0] + " could not reach isolated Emby") from None


def wait_ready(case, timeout=120):
    client = EmbyClient(case)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            info = client.request("GET", "/System/Info/Public")
            if info.get("Version") != case.version:
                raise RuntimeError("official host reports a different version: " + str(info.get("Version")))
            return info
        except RuntimeError as error:
            if "different version" in str(error):
                raise
        time.sleep(1)
    raise RuntimeError("isolated Emby did not become ready within " + str(timeout) + " seconds")


def start(case):
    ensure_root()
    existing = inspect(case)
    if existing:
        verify_container(case, existing)
        if existing["State"]["Running"]:
            return wait_ready(case)
    running = docker("ps", "--filter", "name=codex-subtitle-assistant-", "--format", "{{.Names}}").splitlines()
    running = [name for name in running if name != "codex-subtitle-assistant-browser"]
    if len(running) >= 2:
        raise RuntimeError("two validation containers already run; stop an owned case before starting another")
    if existing:
        docker("start", case.container)
    else:
        root = ROOT / case.version
        root.mkdir(mode=0o700, exist_ok=True)
        for name in ["config", "media", "media/videos", "media/pool"]:
            path = root / name
            path.mkdir(mode=0o700, exist_ok=True)
            os.chown(path, 2, 2)
        docker(
            "run", "-d", "--name", case.container, "--label", "codex.task=" + TASK,
            "--cpus=1", "--memory=1g", "-p", "127.0.0.1:" + str(case.port) + ":8096",
            "--env", "UID=0", "--env", "GID=0", "--env", "GIDLIST=0",
            "--mount", "type=bind,src=" + str(root / "config") + ",dst=/config",
            "--mount", "type=bind,src=" + str(root / "media") + ",dst=/media",
            case.image,
        )
    verify_container(case, inspect(case))
    return wait_ready(case)


def stop(case):
    ensure_root()
    existing = inspect(case)
    if not existing:
        return
    verify_container(case, existing)
    if existing["State"]["Running"]:
        docker("stop", "--time", "20", case.container)


def library_items(value):
    return value if isinstance(value, list) else value.get("Items", [])


def bootstrap(case):
    ensure_root()
    wait_ready(case)
    path = ROOT / case.version / "session.json"
    client = EmbyClient(case)
    if path.exists():
        path.chmod(0o600)
        state = json.loads(path.read_text())
    else:
        state = {"Username": "CodexValidation", "Password": secrets.token_urlsafe(32)}
        write_private(path, state)
        client.request("GET", "/Startup/User")
        client.request("POST", "/Startup/User", {"Name": state["Username"], "Password": state["Password"]})
        client.request("POST", "/Startup/Configuration", {"UICulture": "en-us"})
        client.request("POST", "/Startup/Complete", {})
    authentication = client.request("POST", "/Users/AuthenticateByName", {
        "Username": state["Username"], "Pw": state["Password"],
    })
    state["AccessToken"] = authentication["AccessToken"]
    state["UserId"] = authentication["User"]["Id"]
    write_private(path, state)
    client.token = state["AccessToken"]
    if not authentication["User"].get("Policy", {}).get("IsAdministrator"):
        raise RuntimeError("isolated startup account is not an administrator")
    libraries = library_items(client.request("GET", "/Library/VirtualFolders/Query"))
    matching = [item for item in libraries if item.get("Name") == LIBRARY_NAME]
    if not matching:
        root = ROOT / case.version
        for name in ["media/videos", "media/pool"]:
            directory = root / name
            directory.mkdir(mode=0o700, exist_ok=True)
            os.chown(directory, 2, 2)
        client.request("POST", "/Library/VirtualFolders", {
            "Name": LIBRARY_NAME,
            "CollectionType": "movies",
            "RefreshLibrary": False,
            "Paths": ["/media/videos"],
            "LibraryOptions": {
                "ContentType": "movies",
                "PathInfos": [{"Path": "/media/videos"}],
                "EnableRealtimeMonitor": False,
                "EnableChapterImageExtraction": False,
                "ExtractChapterImagesDuringLibraryScan": False,
                "EnableMarkerDetection": False,
                "DownloadImagesInAdvance": False,
                "SaveLocalMetadata": False,
                "SaveSubtitlesWithMedia": True,
                "SubtitleDownloadLanguages": [],
                "DisabledSubtitleFetchers": [],
                "SubtitleFetcherOrder": [],
                "TypeOptions": [{"Type": "Movie", "MetadataFetchers": [], "ImageFetchers": []}],
            },
        })
        libraries = library_items(client.request("GET", "/Library/VirtualFolders/Query"))
        matching = [item for item in libraries if item.get("Name") == LIBRARY_NAME]
    if len(matching) != 1 or matching[0].get("Locations") != ["/media/videos"]:
        raise RuntimeError("validation library does not have the dedicated fixture path")
    state["LibraryId"] = matching[0]["ItemId"]
    write_private(path, state)
    return client


def fixtures(case):
    target = ROOT / case.version / "media" / "videos" / "ABP-192-CD2-1080p.mp4"
    if not target.exists():
        docker("exec", case.container, "/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", "color=c=black:s=160x90:r=1", "-t", "12",
               "-c:v", "mpeg4", "-q:v", "31", "-an", "/media/videos/" + target.name)
    subtitle = ROOT / case.version / "media" / "pool" / "ABP-192.fixture.srt"
    if not subtitle.exists():
        subtitle.write_text("1\n00:00:00,000 --> 00:00:11,000\n独立验收字幕，不包含真实影片内容。\n", encoding="utf-8")
        os.chown(subtitle, 2, 2)
        subtitle.chmod(0o600)
    return {"VideoStem": target.stem, "VideoBytes": target.stat().st_size, "SubtitleBytes": subtitle.stat().st_size}


def baseline(case):
    public = start(case)
    client = bootstrap(case)
    media = fixtures(case)
    info = inspect(case)
    plugins = client.request("GET", "/Plugins")
    tasks = client.request("GET", "/ScheduledTasks")
    report = {
        "Version": public["Version"],
        "Container": case.container,
        "Image": case.image,
        "ImageId": info["Image"],
        "LoopbackPort": case.port,
        "NanoCpus": info["HostConfig"]["NanoCpus"],
        "Memory": info["HostConfig"]["Memory"],
        "DedicatedAdminAuthenticated": True,
        "Library": LIBRARY_NAME,
        "FixturePath": "/media/videos",
        "Fixtures": media,
        "PluginNames": [item.get("Name") for item in plugins],
        "ScheduledTaskNames": [item.get("Name") for item in tasks],
    }
    write_private(ROOT / "reports" / ("baseline-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "bootstrap", "baseline"])
    parser.add_argument("version", choices=list(CASES))
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("run this driver on NAS through nas-sudo.ps1")
    case = case_for(args.version)
    if args.command == "start":
        print(json.dumps(start(case), ensure_ascii=False))
    elif args.command == "stop":
        stop(case)
        print(json.dumps({"Stopped": case.container}))
    elif args.command == "bootstrap":
        bootstrap(case)
        print(json.dumps({"Version": case.version, "DedicatedAdminAuthenticated": True}))
    else:
        print(json.dumps(baseline(case), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("validation failed: " + str(error), file=sys.stderr)
        sys.exit(1)
