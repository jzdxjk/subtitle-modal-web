#!/usr/bin/env python3
"""Submit a real admin API job to the private mock and observe single-item refresh."""

import argparse
import json
import re
import secrets
import sys
import time
from urllib.request import urlopen
import uuid

from emby_validation import CASES, ROOT, bootstrap, write_private
from business_probe import copy_video, find_movie, movies, set_library_sources


BASE = "http://172.17.0.1:19100"


def scan_signature(client, wait=False):
    deadline = time.monotonic() + 60
    while True:
        task = next(item for item in client.request("GET", "/ScheduledTasks") if item["Name"] == "Scan media library")
        if not wait or task["State"] == "Idle":
            result = task.get("LastExecutionResult") or {}
            return {key: result.get(key) for key in ["StartTimeUtc", "EndTimeUtc", "Status"]}
        if time.monotonic() >= deadline:
            raise RuntimeError("isolated library scan did not finish")
        time.sleep(1)


def probe(case, candidate):
    client = bootstrap(case)
    set_library_sources(client, [], languages=[])
    video, path = copy_video(case, "cloud-" + candidate + "-" + uuid.uuid4().hex[:8], code="FNS-192")
    client.request("POST", "/Library/Refresh", {})
    item = find_movie(client, path)
    before_scan = scan_signature(client, wait=True)
    service_url = BASE + "/cloud/" + case.version
    result = client.request("POST", "/SubtitleAssistant/settings", {
        "CloudServiceUrl": service_url,
        "CloudApiToken": secrets.token_urlsafe(24),
        "CloudPathMappings": "/media/videos=" + str(ROOT / case.version / "media/videos"),
        "AutoDownloadOnNewMedia": False, "Proxy": {"Enabled": False, "Cloud": False},
    })
    if not result.get("Ok"):
        raise RuntimeError("could not configure private cloud fixture service")
    report = {"ServerVersion": case.version, "Candidate": candidate, "VideoStem": video.stem}
    try:
        submitted = client.request("POST", "/SubtitleAssistant/cloud/submit", {"ItemId": item["Id"], "AvCode": "FNS-192"})
        report["SubmitHttpStatus"] = client.last_status
        if client.last_status != 200 or not isinstance(submitted, dict) or not submitted.get("Ok") or not submitted.get("Id"):
            raise RuntimeError("real cloud submit did not return HTTP 200 with a successful JSON job")
        jobs = client.request("GET", "/SubtitleAssistant/cloud/jobs")
        report["JobsHttpStatus"] = client.last_status
        if client.last_status != 200 or not isinstance(jobs, dict) or not jobs.get("Ok") or not isinstance(jobs.get("Jobs"), list):
            raise RuntimeError("real cloud jobs API did not return HTTP 200 with the JSON jobs list")
        deadline = time.monotonic() + 45
        state = None
        streams = []
        while time.monotonic() < deadline:
            with urlopen(service_url + "/api/plugin/jobs", timeout=5) as response:
                backend_jobs = json.load(response)
            backend_job = next(job for job in backend_jobs if job["id"] == submitted["Id"])
            state = backend_job["refresh_state"]
            updated = next(movie for movie in movies(client) if movie.get("Path") == path)
            streams = [stream for stream in updated.get("MediaStreams", [])
                       if stream.get("Type") == "Subtitle" and stream.get("IsExternal")]
            if state == "success" and streams:
                break
            time.sleep(1)
        after_scan = scan_signature(client)
        report.update({
            "MockDoneRefreshState": state,
            "SubtitleWrittenWithCompleteStem": video.with_suffix(".zh-CN.srt").is_file(),
            "ExternalSubtitleStreamsVisible": bool(streams),
            "NoFullLibraryScanDuringRefresh": before_scan == after_scan,
            "BeforeScan": before_scan, "AfterScan": after_scan,
        })
        report["Passed"] = state == "success" and bool(streams) \
            and report["SubtitleWrittenWithCompleteStem"] and report["NoFullLibraryScanDuringRefresh"]
    finally:
        client.request("POST", "/SubtitleAssistant/settings", {
            "CloudServiceUrl": "", "ClearCloudApiToken": True, "Proxy": {"Enabled": False},
        })
    write_private(ROOT / "reports" / (candidate + "-cloud-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-03")
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label is outside the owned fixture namespace")
    report = probe(CASES[args.version], args.candidate)
    print(json.dumps(report, ensure_ascii=False))
    if not report["Passed"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("cloud probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
