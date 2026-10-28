#!/usr/bin/env python3
"""Exercise the completion pipeline with the local provider.

This probe drives
the exact changed path instead: AutoDownloadOnNewMedia -> AfterDelayAsync and
the scheduled MissingSubtitles task -> SubtitleCompletionService.ProcessAsync,
which runs Skip()/StreamCollector before searching and downloading. A local SRT
fixture keeps the whole run isolated with no external network traffic.
"""

import argparse
import json
import re
import shutil
import sys
import time
import uuid

from emby_validation import CASES, ROOT, bootstrap, write_private
from business_probe import copy_video, find_movie, movies, set_library_sources


TASK_KEY = "SubtitleAssistantMissingSubtitles"


def task(client):
    return next(item for item in client.request("GET", "/ScheduledTasks") if item.get("Key") == TASK_KEY)


def run_task(client, expected_status="Completed", timeout=150):
    current = task(client)
    before = (current.get("LastExecutionResult") or {}).get("StartTimeUtc")
    client.request("POST", "/ScheduledTasks/Running/" + current["Id"], {})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = task(client)
        result = current.get("LastExecutionResult") or {}
        if current["State"] == "Idle" and result.get("StartTimeUtc") != before:
            if result.get("Status") != expected_status:
                raise RuntimeError("missing-subtitle task finished with " + str(result.get("Status")))
            return result["Status"]
        time.sleep(0.5)
    raise RuntimeError("missing-subtitle task did not finish")


def prepare(case, candidate, scenario, code):
    client = bootstrap(case)
    root = ROOT / case.version / "media"
    subtitles = root / "subtitles"
    subtitles.mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(root / "subtitle-fixtures" / "ABP-192.fixture.srt", subtitles / (code + ".fixture.srt"))
    configured = client.request("POST", "/SubtitleAssistant/settings", {
        "LocalPaths": "/media/subtitles", "LocalMaxResults": 5, "ThunderMaxResults": 10,
        "AutoDownloadOnNewMedia": scenario == "new",
        "Proxy": {"Enabled": False, "ClearPassword": True, "Username": ""},
    })
    if not configured.get("Ok"):
        raise RuntimeError("could not configure local completion fixture")
    # No download languages: this stops Emby's native subtitle download during the
    # library scan, leaving only the plugin's own completion pipeline to act.
    sources = set_library_sources(client, ["本地字幕"], languages=[])
    started = time.monotonic()
    video, path = copy_video(case, scenario + "-" + candidate + "-" + uuid.uuid4().hex[:8], code=code,
                             stem=code + "-CD2-1080p")
    preexisting = None
    if scenario == "existing":
        preexisting = video.with_name(video.stem + ".jpn.srt")
        shutil.copyfile(root / "subtitle-fixtures" / "ABP-192.fixture.srt",preexisting)
    client.request("POST", "/Library/Refresh", {})
    find_movie(client, path)
    initial_sidecars = list(video.parent.glob(video.stem + ".*.srt"))
    if preexisting is None and initial_sidecars:
        raise RuntimeError("fixture already has a subtitle before automation starts")
    if preexisting is not None and initial_sidecars != [preexisting]:
        raise RuntimeError("existing-subtitle fixture contains unexpected sidecars")
    return client, video, path, sources, started, preexisting


def observe(client, video, path, timeout=95, any_language=False):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        saved = list(video.parent.glob(video.stem + ".*.srt"))
        item = next(movie for movie in movies(client) if movie.get("Path") == path)
        streams = [stream for stream in item.get("MediaStreams", [])
                   if stream.get("Type") == "Subtitle" and stream.get("IsExternal")
                   and (any_language or (stream.get("Language") or "").lower().startswith("zh"))]
        if saved and streams:
            return saved, streams
        time.sleep(1)
    return list(video.parent.glob(video.stem + ".*.srt")), []


def probe(case, candidate, scenario):
    code = "MEYD-040" if scenario == "backfill" else "IPX-697"
    client, video, path, sources, started, preexisting = prepare(case, candidate, scenario, code)
    report = {"ServerVersion": case.version, "Candidate": candidate, "Scenario": scenario,
              "Provider": "本地字幕", "VideoStem": video.stem, "NativeLibrarySources": sources}
    try:
        if scenario in {"backfill","existing"}:
            report["NativeTaskStatus"] = run_task(client)
        saved, streams = observe(client, video, path,any_language=scenario == "existing")
        expected = (ROOT / case.version / "media" / "subtitles" / (code + ".fixture.srt")).read_bytes()
        report.update({
            "SavedSubtitleNames": [file.name for file in saved],
            "CompleteStemPreserved": len(saved) == 1 and saved[0].name.startswith(video.stem + "."),
            "OriginalBytesPreserved": len(saved) == 1 and saved[0].read_bytes() == expected,
            "ExternalSubtitleStreamsVisible": bool(streams),
            "ExternalSubtitleLanguages": [stream.get("Language") for stream in streams],
            "SecondsSinceFixtureCreated": round(time.monotonic() - started, 1),
        })
        if scenario == "new":
            report["SixtySecondDelayObserved"] = report["SecondsSinceFixtureCreated"] >= 55
        elif scenario == "backfill":
            run_task(client)
            report["ExistingChineseSubtitleSkipsDownload"] = len(
                list(video.parent.glob(video.stem + ".*.srt"))) == len(saved)
        else:
            report["ExistingAnyLanguageSubtitleSkipsDownload"] = preexisting is not None and \
                preexisting.exists() and preexisting.read_bytes() == expected and saved == [preexisting]
        report["Passed"] = all(report[key] for key in [
            "CompleteStemPreserved", "OriginalBytesPreserved", "ExternalSubtitleStreamsVisible",
        ])
        if scenario == "new":
            report["Passed"] = report["Passed"] and report["SixtySecondDelayObserved"]
        elif scenario == "backfill":
            report["Passed"] = report["Passed"] and report["NativeTaskStatus"] == "Completed" \
                and report["ExistingChineseSubtitleSkipsDownload"]
        else:
            report["Passed"] = report["Passed"] and report["NativeTaskStatus"] == "Completed" \
                and report["ExistingAnyLanguageSubtitleSkipsDownload"]
    finally:
        client.request("POST", "/SubtitleAssistant/settings", {
            "AutoDownloadOnNewMedia": False, "Proxy": {"Enabled": False, "ClearPassword": True, "Username": ""},
        })
    write_private(ROOT / "reports" / (candidate + "-completion-" + scenario + "-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-10")
    parser.add_argument("--scenario", choices=["backfill", "new", "existing"], default="new")
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
        print("completion probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
