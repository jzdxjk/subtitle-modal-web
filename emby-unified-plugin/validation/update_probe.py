#!/usr/bin/env python3
"""Native scheduled update against a private PE-version-only candidate."""

import argparse
import hashlib
import json
import re
import sys

from emby_validation import CASES, ROOT, bootstrap, inspect, write_private
from plugin_smoke import PLUGIN_ID
from automation_probe import run_task
from proxy_probe import events


SOURCE_SHA = "2694f2991f040f5603d88ab6d250ccf9650e8c7aa3a173bab848726ee981de31"
UPGRADE_SHA = "df0916e3cf49b64447df71846162d597e15ba4fb4678b142aa4f88aaaf635a85"
TASK_KEY = "SubtitleAssistantUpdate"
BASE = "http://172.17.0.1:19100"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_downloads():
    return len([event for event in events() if event.get("Path") == "/updates/Emby.SubtitleAssistant.dll"
                and not event.get("Proxy")])


def probe(case, candidate, source_sha, upgrade_sha):
    client = bootstrap(case)
    destination = ROOT / case.version / "config/plugins/Emby.SubtitleAssistant.dll"
    package = ROOT / "artifacts/Emby.SubtitleAssistant.dll"
    manifest_path = ROOT / "artifacts/update.json"
    if digest(destination) != source_sha or digest(package) != upgrade_sha:
        raise RuntimeError("update test artifacts differ from their pinned original/upgrade hashes")
    original = client.request("GET", "/Plugins/" + PLUGIN_ID + "/Configuration")
    credentials = json.loads((ROOT / "mock-session.json").read_text())
    started = inspect(case)["State"]["StartedAt"]
    staging = destination.parent / ".subtitle-assistant-update"
    original_backups = set(staging.glob("*.bak"))
    manifest = {
        "version": "1.0.0.1", "download_url": BASE + "/updates/Emby.SubtitleAssistant.dll",
        "sha256": "0" * 64, "plugin_id": PLUGIN_ID, "channel": "stable",
        "minimum_server_versions": {"4.8": "4.8.11.0", "4.9": "4.9.1.80", "4.10": "4.10.0.40"},
    }
    report = {"ServerVersion": case.version, "Candidate": candidate,
              "OriginalPinnedSha256": source_sha, "UpgradeSha256": upgrade_sha}
    result = client.request("POST", "/SubtitleAssistant/settings", {
        "UpdateManifestUrl": BASE + "/updates/update.json",
        "Proxy": {"Enabled": True, "Address": "http://172.17.0.1:19101",
                  "Username": credentials["Username"], "Password": credentials["Password"],
                  "Thunder": True, "Pool": False, "Cloud": False, "Updates": True,
                  "BypassLocal": False, "BypassHosts": ""},
    })
    if not result.get("Ok"):
        raise RuntimeError("could not configure private native update fixture")
    try:
        pending_before = bool(client.request("GET", "/System/Info").get("HasPendingRestart"))
        write_private(manifest_path, manifest)
        report["RejectedChecksumTaskStatus"] = run_task(client, TASK_KEY, "Failed")
        report["RejectedChecksumPreservesOriginal"] = digest(destination) == source_sha
        report["RejectedChecksumPreservesBackupSet"] = set(staging.glob("*.bak")) == original_backups
        report["RejectedChecksumDoesNotIntroduceRestart"] = \
            bool(client.request("GET", "/System/Info").get("HasPendingRestart")) == pending_before
        manifest["sha256"] = upgrade_sha
        write_private(manifest_path, manifest)
        proxy_before = len([event for event in events() if event.get("Proxy") == "HTTP" and event.get("TargetAllowed")])
        report["InstallTaskStatus"] = run_task(client, TASK_KEY)
        report["DiskMatchesUpgrade"] = digest(destination) == upgrade_sha
        report["OriginalBackupRetained"] = any(digest(path) == source_sha for path in staging.glob("*.bak"))
        report["PreexistingBackupsRetained"] = original_backups.issubset(set(staging.glob("*.bak")))
        report["TemporaryCandidatesCleaned"] = not list(staging.glob("candidate-*.bin"))
        report["PendingRestart"] = bool(client.request("GET", "/System/Info").get("HasPendingRestart"))
        report["ContainerNotRestartedAutomatically"] = inspect(case)["State"]["StartedAt"] == started
        report["UpdateTrafficUsedIndependentProxy"] = \
            len([event for event in events() if event.get("Proxy") == "HTTP" and event.get("TargetAllowed")]) > proxy_before
        downloads = package_downloads()
        run_task(client, TASK_KEY)
        report["RepeatCheckDoesNotDownloadPackageAgain"] = package_downloads() == downloads
        report["Passed"] = all(report[key] for key in [
            "RejectedChecksumPreservesOriginal", "RejectedChecksumPreservesBackupSet",
            "RejectedChecksumDoesNotIntroduceRestart", "DiskMatchesUpgrade", "OriginalBackupRetained",
            "PreexistingBackupsRetained", "TemporaryCandidatesCleaned", "PendingRestart",
            "ContainerNotRestartedAutomatically", "UpdateTrafficUsedIndependentProxy",
            "RepeatCheckDoesNotDownloadPackageAgain",
        ])
    finally:
        proxy = dict(original.get("Proxy") or {})
        proxy["ClearPassword"] = not bool(proxy.get("Password"))
        client.request("POST", "/SubtitleAssistant/settings", {
            "UpdateManifestUrl": original["UpdateManifestUrl"], "Proxy": proxy,
        })
    write_private(ROOT / "reports" / (candidate + "-update-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-03")
    parser.add_argument("--source-sha256", default=SOURCE_SHA)
    parser.add_argument("--upgrade-sha256", default=UPGRADE_SHA)
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label is outside the owned report namespace")
    report = probe(CASES[args.version], args.candidate, args.source_sha256, args.upgrade_sha256)
    print(json.dumps(report, ensure_ascii=False))
    if not report["Passed"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("update probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
