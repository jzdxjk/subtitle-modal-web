#!/usr/bin/env python3
"""Install a hash-pinned candidate only into owned isolated hosts, then probe."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

from emby_validation import (
    CASES, ROOT, EmbyClient, bootstrap, case_for, ensure_root, inspect,
    docker, start, stop, verify_container, write_private,
)


PLUGIN_ID = "76cd4168-e0b3-4aac-8a52-5cb638121744"
PROVIDERS = ["本地字幕", "迅雷字幕"]
TASK_KEYS = ["SubtitleAssistantMissingSubtitles", "SubtitleAssistantUpdate"]


def install(case, filename, expected_sha256):
    ensure_root()
    if Path(filename).name != filename or not filename.endswith(".dll"):
        raise ValueError("candidate filename must be a DLL basename in the owned incoming directory")
    source = ROOT / "incoming" / filename
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256) or digest != expected_sha256.lower():
        raise RuntimeError("candidate SHA-256 differs from the pinned artifact")
    existing = inspect(case)
    if not existing:
        raise RuntimeError("run the stock baseline before installing a candidate")
    verify_container(case, existing)
    stop(case)
    directory = ROOT / case.version / "config" / "plugins"
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chown(directory, 2, 2)
    destination = directory / "Emby.SubtitleAssistant.dll"
    shutil.copyfile(source, destination)
    destination.chmod(0o644)
    os.chown(destination, 2, 2)
    if "UID=0" not in existing["Config"].get("Env", []):
        # UGOS projects these task-private bind paths as mode 111 to non-root.
        # Retain all bind data; replace only the verified, stopped test container.
        docker("rm", case.container)
    start(case)
    return digest


def probe(case, candidate):
    client = bootstrap(case)
    plugins = client.request("GET", "/Plugins")
    found = [item for item in plugins if str(item.get("Id", "")).lower() == PLUGIN_ID]
    if len(found) != 1:
        raise RuntimeError("combined plugin did not register exactly once in the actual host")
    settings = client.request("GET", "/SubtitleAssistant/settings")
    page = client.request("GET", "/web/ConfigurationPage?name=subtitleassistant")
    script = client.request("GET", "/web/ConfigurationPage?name=subtitleassistantjs")
    if settings.get("Version") != "1.0.0.10":
        raise RuntimeError("combined plugin did not load version 1.0.0.10")
    if not isinstance(page, str) or len(re.findall(r'role="tab"', page)) != 4:
        raise RuntimeError("native configuration page did not expose four tabs")
    if "海南鸡字幕已上传至迅雷字幕库" not in page or "搜索命中时优先展示海南鸡字幕" not in page:
        raise RuntimeError("Thunder settings page is missing the ChickenRice priority note")
    if not isinstance(script, str) or "SubtitleAssistant" not in script:
        raise RuntimeError("native configuration controller resource did not load")
    available = client.request("GET", "/Libraries/AvailableOptions")
    providers = available.get("SubtitleFetchers", [])
    names = [item.get("Name") for item in providers]
    if any(names.count(name) != 1 for name in PROVIDERS):
        raise RuntimeError("native library options do not register the two subtitle providers once")
    if "海南鸡字幕" in names:
        raise RuntimeError("retired ChickenRice pool source is still registered by the combined plugin")
    if any(key in settings for key in ["PoolUrl", "PoolMaxResults", "PoolTimeoutSeconds"]):
        raise RuntimeError("retired public-pool configuration is still exposed")
    if not 1 <= int(settings.get("ThunderMaxResults", 0)) <= 10:
        raise RuntimeError("Thunder display limit is outside the 1..10 range")
    tasks = client.request("GET", "/ScheduledTasks")
    selected_tasks = [item for item in tasks if item.get("Key") in TASK_KEYS]
    if len(selected_tasks) != 2:
        raise RuntimeError("native scheduled-task registry does not expose both plugin tasks")
    denied = False
    try:
        EmbyClient(case).request("GET", "/SubtitleAssistant/settings")
    except RuntimeError as error:
        denied = "HTTP 401" in str(error) or "HTTP 403" in str(error)
    if not denied:
        raise RuntimeError("settings API did not reject an unauthenticated client")
    report = {
        "ServerVersion": case.version,
        "Candidate": candidate,
        "PluginVersion": found[0].get("Version"),
        "SettingsVersion": settings.get("Version"),
        "PluginId": PLUGIN_ID,
        "ServiceUser": "0:0",
        "DllSha256": hashlib.sha256((ROOT / case.version / "config/plugins/Emby.SubtitleAssistant.dll").read_bytes()).hexdigest(),
        "AdminSettingsApi": True,
        "UnauthenticatedSettingsDenied": True,
        "ConfigurationTabs": 4,
        "ChickenRicePriorityNote": True,
        "RetiredPoolSourceAbsent": "海南鸡字幕" not in names,
        "ControllerLoaded": True,
        "Providers": [{key: item[key] for key in ["Id", "Name", "DisplayName"] if key in item}
                      for item in providers if item.get("Name") in PROVIDERS],
        "Tasks": [{key: item[key] for key in ["Id", "Key", "Name", "Triggers"] if key in item}
                  for item in selected_tasks],
        "DisplayLimits": {key: settings[key] for key in ["LocalMaxResults", "ThunderMaxResults"]},
    }
    write_private(ROOT / "reports" / (candidate + "-smoke-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-01")
    parser.add_argument("--install")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label must stay inside the owned report namespace")
    case = case_for(args.version)
    if args.install:
        if not args.sha256:
            raise ValueError("installation requires the pinned candidate SHA-256")
        install(case, args.install, args.sha256)
    print(json.dumps(probe(case, args.candidate), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("plugin smoke failed: " + str(error), file=sys.stderr)
        sys.exit(1)
