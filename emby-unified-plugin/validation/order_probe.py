#!/usr/bin/env python3
"""Probe live manual-search provider order on an owned isolated Emby host."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
from urllib.parse import urlencode

from emby_validation import CASES, ROOT, bootstrap, library_items, start, stop, write_private
from business_probe import copy_video, find_movie, set_library_sources


def fetcher_names(client):
    return [item["Name"] for item in client.request("GET", "/Libraries/AvailableOptions")["SubtitleFetchers"]]


def set_plugin_order(client, order):
    result = client.request("POST", "/SubtitleAssistant/settings", {"ProviderDisplayOrder": order})
    if not result.get("Ok") or result["Settings"]["ProviderDisplayOrder"] != order:
        raise RuntimeError("plugin source order did not persist")
    return result["Settings"]["ProviderDisplayOrder"]


def search(client, item, media_source_id):
    query = urlencode({"MediaSourceId": media_source_id, "IsPerfectMatch": "false"})
    return client.request("GET", "/Items/" + item["Id"] + "/RemoteSearch/Subtitles/zh-CN?" + query, timeout=120)


def first_positions(results):
    positions = []
    for result in results:
        name = result.get("ProviderName")
        if name and name not in positions:
            positions.append(name)
    return positions


def prepare(case):
    client = bootstrap(case)
    root = ROOT / case.version / "media"
    subtitle_root = root / "subtitles"
    subtitle_root.mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(root / "subtitle-fixtures/ABP-192.fixture.srt", subtitle_root / "SSIS-157.fixture.srt")
    configured = client.request("POST", "/SubtitleAssistant/settings", {
        "LocalPaths": "/media/subtitles", "LocalMaxResults": 5, "ThunderMaxResults": 10,
        "ThunderTimeoutSeconds": 20, "AutoDownloadOnNewMedia": False,
        "Proxy": {"Enabled": False, "ClearPassword": True, "Username": ""},
    })
    if not configured.get("Ok"):
        raise RuntimeError("could not configure local fixture path")
    sources = set_library_sources(client, ["本地字幕", "迅雷字幕"], languages=[])
    video, path = copy_video(case, "order-" + uuid.uuid4().hex[:8], code="SSIS-157", stem="SSIS-157-c-无码破解")
    client.request("POST", "/Library/Refresh", {})
    item = find_movie(client, path)
    media_source = next(source for source in item["MediaSources"] if source["Path"] == path)
    set_plugin_order(client, ["Local", "Thunder"])
    stop(case)
    start(case)
    client = bootstrap(case)
    item = find_movie(client, path)
    media_source = next(source for source in item["MediaSources"] if source["Path"] == path)
    return client, item, media_source["Id"], sources


def probe(case, candidate):
    client, item, media_source_id, sources = prepare(case)
    observations = []

    def record(label, plugin_order, library_order):
        saved = set_plugin_order(client, plugin_order)
        set_library_sources(client, ["本地字幕", "迅雷字幕"], order=library_order, languages=[])
        fetchers = fetcher_names(client)
        results = search(client, item, media_source_id)
        observations.append({
            "Label": label,
            "ConfiguredOrder": saved,
            "LibraryOrder": library_order,
            "AvailableFetcherOrder": fetchers,
            "ResultCount": len(results),
            "ProviderSequence": first_positions(results),
        })

    record("plugin-local_library-local", ["Local", "Thunder"], ["本地字幕", "迅雷字幕"])
    record("plugin-local_library-thunder", ["Local", "Thunder"], ["迅雷字幕", "本地字幕"])
    record("plugin-thunder_library-thunder", ["Thunder", "Local"], ["迅雷字幕", "本地字幕"])
    record("plugin-thunder_library-local", ["Thunder", "Local"], ["本地字幕", "迅雷字幕"])

    stop(case)
    start(case)
    restarted = bootstrap(case)
    restarted_fetchers = fetcher_names(restarted)
    item = find_movie(restarted, item["Path"])
    media_source_id = next(source["Id"] for source in item["MediaSources"] if source["Path"] == item["Path"])
    after_restart = search(restarted, item, media_source_id)
    sequences = [item["ProviderSequence"] for item in observations] + [first_positions(after_restart)]
    both_sources = all("本地字幕" in sequence and "迅雷字幕" in sequence for sequence in sequences)
    restart_starts_thunder = first_positions(after_restart)[:1] == ["迅雷字幕"]
    report = {
        "ServerVersion": case.version,
        "Candidate": candidate,
        "ObservationsWithoutRestart": observations,
        "AvailableFetcherOrderAfterRestart": restarted_fetchers,
        "ProviderSequenceAfterRestart": first_positions(after_restart),
        "LibraryOrderControlsSearch": observations[0]["ProviderSequence"] != observations[1]["ProviderSequence"],
        "PluginOrderChangesFetchersLive": observations[0]["AvailableFetcherOrder"] != observations[3]["AvailableFetcherOrder"],
        "BothSourcesPresent": both_sources,
        "RestartUsesConfiguredThunderFirst": restart_starts_thunder,
        "Passed": both_sources and restart_starts_thunder,
    }
    write_private(ROOT / "reports" / (candidate + "-order-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-06")
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("run this driver on NAS through nas-sudo.ps1")
    report = probe(CASES[args.version], args.candidate)
    print(json.dumps(report, ensure_ascii=False))
    if not report["Passed"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("order probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
