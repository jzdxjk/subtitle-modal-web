#!/usr/bin/env python3
"""Observe native scheduled/new-item completion beyond the five displayed results."""

import argparse
import json
import re
import sys
import time
from urllib.parse import urlencode
import uuid

from emby_validation import CASES, ROOT, bootstrap, write_private
from business_probe import copy_video, find_movie, movies, set_library_sources
from cloud_probe import scan_signature
from mock_services import subtitle_bytes
from proxy_probe import events


TASK_KEY = "SubtitleAssistantMissingSubtitles"


def task(client, key=TASK_KEY):
    return next(item for item in client.request("GET", "/ScheduledTasks") if item.get("Key") == key)


def run_task(client, key=TASK_KEY, expected_status="Completed"):
    before = (task(client, key).get("LastExecutionResult") or {}).get("StartTimeUtc")
    client.request("POST", "/ScheduledTasks/Running/" + task(client, key)["Id"], {})
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        current = task(client, key)
        result = current.get("LastExecutionResult") or {}
        if current["State"] == "Idle" and result.get("StartTimeUtc") != before:
            if result.get("Status") != expected_status:
                raise RuntimeError("native subtitle completion task did not complete successfully")
            return result["Status"]
        time.sleep(0.5)
    raise RuntimeError("native subtitle completion task did not finish")


def prepare(client, case, candidate, scenario, code):
    credentials = json.loads((ROOT / "mock-session.json").read_text())
    result = client.request("POST", "/SubtitleAssistant/settings", {
        "PoolUrl": "http://172.17.0.1:19100/pool/fallback", "PoolMaxResults": 5,
        "LocalPaths": "/media/subtitles", "AutoDownloadOnNewMedia": scenario == "new",
        "Proxy": {"Enabled": True, "Address": "http://172.17.0.1:19101",
                  "Username": credentials["Username"], "Password": credentials["Password"],
                  "Thunder": True, "Pool": False, "Cloud": False, "Updates": False, "BypassLocal": False},
    })
    if not result.get("Ok"):
        raise RuntimeError("could not configure fallback-only subtitle fixture")
    set_library_sources(client, ["海南鸡字幕"], languages=[])
    started = time.monotonic()
    video, path = copy_video(case, scenario + "-" + candidate + "-" + uuid.uuid4().hex[:8], code=code)
    client.request("POST", "/Library/Refresh", {})
    item = find_movie(client, path)
    scan_signature(client, wait=True)
    sources = set_library_sources(client, ["海南鸡字幕"], languages=["zh-CN"])
    if list(video.parent.glob(video.stem + ".*.srt")):
        raise RuntimeError("fixture already has a subtitle before plugin automation starts")
    return video, path, item, sources, started


def observe(client, video, path, timeout=95):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        saved = list(video.parent.glob(video.stem + ".*.srt"))
        item = next(movie for movie in movies(client) if movie.get("Path") == path)
        streams = [stream for stream in item.get("MediaStreams", [])
                   if stream.get("Type") == "Subtitle" and stream.get("IsExternal")]
        if saved and streams:
            return saved, streams
        time.sleep(1)
    return list(video.parent.glob(video.stem + ".*.srt")), []


def summarize_window(start):
    window = events()[start:]
    downloads = [event["Path"] for event in window
                 if event.get("Method") == "GET" and event.get("Path", "").startswith("/pool/fallback/")
                 and event.get("Path", "").endswith("/download")]
    return {
        "PoolDownloadRequests": len(downloads),
        "SixthCandidateRequested": any(path.endswith("000000000006/download") for path in downloads),
        "FirstFiveCandidatesRequested": all(any(path.endswith(str(index).zfill(12) + "/download") for path in downloads)
                                              for index in range(1, 6)),
        "DisabledRemoteSourceProxyRequests": len([event for event in window if event.get("Proxy")]),
    }


def probe(case, candidate, scenario):
    client = bootstrap(case)
    code = "MEYD-040" if scenario == "backfill" else "IPX-697"
    video, path, item, sources, started = prepare(client, case, candidate, scenario, code)
    report = {"ServerVersion": case.version, "Candidate": candidate, "Scenario": scenario,
              "VideoStem": video.stem, "NativeLibrarySources": sources}
    try:
        if scenario == "backfill":
            source = next(source for source in item["MediaSources"] if source["Path"] == path)
            query = urlencode({"MediaSourceId": source["Id"], "IsPerfectMatch": "false"})
            results = client.request("GET", "/Items/" + item["Id"] + "/RemoteSearch/Subtitles/zh-CN?" + query)
            report["DisplayedPoolResults"] = len([value for value in results if value.get("ProviderName") == "海南鸡字幕"])
        before_scan = scan_signature(client, wait=True)
        event_start = len(events())
        if scenario == "backfill":
            report["NativeTaskStatus"] = run_task(client)
        saved, streams = observe(client, video, path)
        report.update(summarize_window(event_start))
        report.update({
            "SavedSubtitleNames": [file.name for file in saved],
            "CompleteStemPreserved": len(saved) == 1 and saved[0].name.startswith(video.stem + "."),
            "SixthCandidateBytesSaved": len(saved) == 1 and saved[0].read_bytes() == subtitle_bytes(6),
            "ExternalSubtitleStreamsVisible": bool(streams),
            "NoFullLibraryScanOnCompletion": before_scan == scan_signature(client),
        })
        if scenario == "new":
            report["SecondsSinceNewFixtureCreated"] = round(time.monotonic() - started, 1)
            report["SixtySecondDelayObserved"] = report["SecondsSinceNewFixtureCreated"] >= 55
        else:
            second_start = len(events())
            run_task(client)
            report["ExistingChineseSubtitleSkipsDownload"] = summarize_window(second_start)["PoolDownloadRequests"] == 0
        report["Passed"] = all(report[key] for key in [
            "CompleteStemPreserved", "SixthCandidateBytesSaved", "ExternalSubtitleStreamsVisible",
            "FirstFiveCandidatesRequested", "SixthCandidateRequested", "NoFullLibraryScanOnCompletion",
        ]) and report["DisabledRemoteSourceProxyRequests"] == 0
        if scenario == "new":
            report["Passed"] = report["Passed"] and report["SixtySecondDelayObserved"]
        else:
            report["Passed"] = report["Passed"] and report["DisplayedPoolResults"] == 5 \
                and report["ExistingChineseSubtitleSkipsDownload"]
    finally:
        client.request("POST", "/SubtitleAssistant/settings", {
            "AutoDownloadOnNewMedia": False, "Proxy": {"Enabled": False, "ClearPassword": True, "Username": ""},
        })
    write_private(ROOT / "reports" / (candidate + "-automation-" + scenario + "-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-03")
    parser.add_argument("--scenario", choices=["backfill", "new"], default="backfill")
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label is outside the owned fixture namespace")
    report = probe(CASES[args.version], args.candidate, args.scenario)
    print(json.dumps(report, ensure_ascii=False))
    if not report["Passed"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("automation probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
