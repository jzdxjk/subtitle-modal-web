#!/usr/bin/env python3
"""Verify native new-item/backfill downloads and single-item subtitle refresh."""

import argparse
import json
import re
import sys
import time
import uuid
from urllib.parse import urlencode

from emby_validation import CASES, ROOT, bootstrap, write_private
from business_probe import copy_video, find_movie, movies, set_library_sources
from cloud_probe import scan_signature


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
    result = client.request("POST", "/SubtitleAssistant/settings", {
        "LocalPaths": "/media/subtitles", "LocalMaxResults": 5, "ThunderMaxResults": 10,
        "AutoDownloadOnNewMedia": scenario == "new",
        "Proxy": {"Enabled": False, "ClearPassword": True, "Username": ""},
    })
    if not result.get("Ok"):
        raise RuntimeError("could not configure local subtitle fixture")
    subtitle_root = ROOT / case.version / "media/subtitles"
    subtitle_root.mkdir(mode=0o700, exist_ok=True)
    fixture = ROOT / case.version / "media/subtitle-fixtures/ABP-192.fixture.srt"
    subtitle = subtitle_root / (code + ".zh-CN.srt")
    subtitle.write_bytes(fixture.read_bytes())
    # Keep Emby's native auto-downloader from saving the same fixture during the
    # scan; the plugin completion service selects Chinese when this list is empty.
    sources = set_library_sources(client, ["本地字幕"], languages=[])
    started = time.monotonic()
    stem = "abc-123-4k-无码破解" if scenario == "new" else None
    video, path = copy_video(case, scenario + "-" + candidate + "-" + uuid.uuid4().hex[:8], code=code, stem=stem)
    client.request("POST", "/Library/Refresh", {})
    item = find_movie(client, path)
    scan_signature(client, wait=True)
    if list(video.parent.glob(video.stem + ".*.srt")):
        raise RuntimeError("fixture already has a subtitle before plugin automation starts")
    return video, path, item, sources, subtitle, started


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


def probe(case, candidate, scenario):
    client = bootstrap(case)
    code = "MEYD-040" if scenario == "backfill" else "ABC-123"
    video, path, item, sources, fixture, started = prepare(client, case, candidate, scenario, code)
    report = {"ServerVersion": case.version, "Candidate": candidate, "Scenario": scenario,
              "VideoStem": video.stem, "NativeLibrarySources": sources}
    try:
        if scenario == "backfill":
            source = next(source for source in item["MediaSources"] if source["Path"] == path)
            query = urlencode({"MediaSourceId": source["Id"], "IsPerfectMatch": "false"})
            results = client.request("GET", "/Items/" + item["Id"] + "/RemoteSearch/Subtitles/zh-CN?" + query)
            report["DisplayedLocalResults"] = len([value for value in results if value.get("ProviderName") == "本地字幕"])
        before_scan = scan_signature(client, wait=True)
        if scenario == "backfill":
            report["NativeTaskStatus"] = run_task(client)
        saved, streams = observe(client, video, path)
        content_equal = len(saved) == 1 and saved[0].read_bytes() == fixture.read_bytes()
        native_name = video.stem + ".zh-CN.srt"
        legacy_zh_name = video.stem + ".zh.srt"
        report.update({
            "SavedSubtitleNames": [file.name for file in saved],
            "CompleteStemPreserved": len(saved) == 1 and saved[0].name.startswith(video.stem + "."),
            "NativeLanguageSuffixPreserved": len(saved) == 1 and saved[0].name in {native_name, legacy_zh_name},
            "NativeLanguageSuffix": "zh-CN" if len(saved) == 1 and saved[0].name == native_name else
                "zh" if len(saved) == 1 and saved[0].name == legacy_zh_name else None,
            "OriginalBytesPreserved": content_equal,
            "ExternalSubtitleStreamsVisible": bool(streams),
            "NoFullLibraryScanOnCompletion": before_scan == scan_signature(client),
        })
        if scenario == "new":
            report["SecondsSinceNewFixtureCreated"] = round(time.monotonic() - started, 1)
            report["SixtySecondDelayObserved"] = report["SecondsSinceNewFixtureCreated"] >= 55
        else:
            before = saved[0].stat().st_mtime_ns if saved else None
            run_task(client)
            after = saved[0].stat().st_mtime_ns if saved else None
            report["ExistingChineseSubtitleSkipsRewrite"] = before == after
        report["Passed"] = all(report[key] for key in [
            "CompleteStemPreserved", "NativeLanguageSuffixPreserved", "OriginalBytesPreserved",
            "ExternalSubtitleStreamsVisible", "NoFullLibraryScanOnCompletion",
        ])
        if scenario == "new":
            report["Passed"] = report["Passed"] and report["SixtySecondDelayObserved"]
        else:
            report["Passed"] = report["Passed"] and report["DisplayedLocalResults"] == 1 \
                and report["ExistingChineseSubtitleSkipsRewrite"]
    finally:
        client.request("POST", "/SubtitleAssistant/settings", {"AutoDownloadOnNewMedia": False})
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
