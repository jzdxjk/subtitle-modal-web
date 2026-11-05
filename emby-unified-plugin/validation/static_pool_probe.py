#!/usr/bin/env python3
"""Exercise the built-in static pool through a real isolated Emby host."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time
import uuid
from urllib.parse import quote, urlencode

from business_probe import find_movie, movies, set_library_sources
from emby_validation import CASES, ROOT, bootstrap, write_private


BUILT_IN_POOL_STATIC_URL = "https://chickenrice-subtitle-static-00.jzdxjk.workers.dev"
TEST_CODE = "GAREA-763"
EXPECTED_SHA256 = "4fcf99fe62563f6d699b6d9866127894730d79ee8b1d6b130ce20ba5d5f0febe"


def decode_payload(subtitle_id):
    marker = subtitle_id.find("sa1.")
    if marker < 0:
        raise RuntimeError("native subtitle result did not contain a signed static-pool identifier")
    token = subtitle_id[marker + 4:].split(".", 1)[0]
    token += "=" * ((4 - len(token) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(token).decode("utf-8"))


def copy_fixture(case):
    root = ROOT / case.version / "media" / "videos"
    source = root / "ABP-192-CD2-1080p.mp4"
    if not source.is_file():
        raise RuntimeError("baseline video fixture is missing")
    directory = root / ("static-pool-" + uuid.uuid4().hex[:8])
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / (TEST_CODE + "-CD2-1080p.mp4")
    shutil.copyfile(source, target)
    return target, "/media/videos/" + directory.name + "/" + target.name


def probe(case, candidate):
    client = bootstrap(case)
    configured = client.request("POST", "/SubtitleAssistant/settings", {
        "PoolStaticUrl": "",
        "PoolMaxResults": 5,
        "PoolTimeoutSeconds": 30,
        "AutoDownloadOnNewMedia": False,
        "Proxy": {"Enabled": False},
    })
    if not configured.get("Ok"):
        raise RuntimeError("could not save settings: " + str(configured.get("Error")))
    built_in_visible = configured["Settings"].get("PoolStaticUrl") == BUILT_IN_POOL_STATIC_URL
    if not built_in_visible:
        raise RuntimeError("blank static-pool setting did not expose the built-in URL")

    sources = set_library_sources(client, ["海南鸡字幕"], languages=["zh-CN"])
    video, path = copy_fixture(case)
    client.request("POST", "/Library/Refresh", {})
    item = find_movie(client, path)
    media_source = next(source for source in item["MediaSources"] if source["Path"] == path)
    query = urlencode({"MediaSourceId": media_source["Id"], "IsPerfectMatch": "false"})
    results = client.request("GET", "/Items/" + item["Id"] + "/RemoteSearch/Subtitles/zh-CN?" + query)
    selected = [
        result for result in results
        if result.get("ProviderName") == "海南鸡字幕" and TEST_CODE in (result.get("Name") or "")
    ]
    if len(selected) != 1:
        raise RuntimeError("native static-pool search did not return GAREA-763 exactly once")
    payload = decode_payload(selected[0]["Id"])
    if payload.get("ContentHash") != EXPECTED_SHA256:
        raise RuntimeError("native static-pool result carries an unexpected content hash")

    client.request(
        "POST",
        "/Items/" + item["Id"] + "/RemoteSearch/Subtitles/" + quote(selected[0]["Id"], safe="")
        + "?" + urlencode({"MediaSourceId": media_source["Id"]}),
        {},
    )
    deadline = time.monotonic() + 30
    saved = []
    while time.monotonic() < deadline:
        saved = list(video.parent.glob(video.stem + ".*.srt"))
        if saved:
            time.sleep(2)
            saved = list(video.parent.glob(video.stem + ".*.srt"))
            break
        time.sleep(1)
    if not saved:
        raise RuntimeError("native static-pool download did not produce an SRT")
    downloaded_hashes = {hashlib.sha256(path.read_bytes()).hexdigest() for path in saved}
    if downloaded_hashes != {EXPECTED_SHA256}:
        raise RuntimeError("one or more downloaded subtitle files do not match the static-pool SHA-256")

    report = {
        "ServerVersion": case.version,
        "Candidate": candidate,
        "Scenario": "BuiltInStaticPoolSearchAndDownload",
        "BuiltInPoolStaticUrl": BUILT_IN_POOL_STATIC_URL,
        "BuiltInVisibleAfterBlankSave": built_in_visible,
        "NativeLibrarySources": sources,
        "RequestedCode": TEST_CODE,
        "NativeStaticPoolResults": len(selected),
        "ProviderName": selected[0].get("ProviderName"),
        "ResultName": selected[0].get("Name"),
        "SignedPayloadContentHash": payload.get("ContentHash"),
        "SavedSubtitleNames": [path.name for path in saved],
        "DownloadedBytes": sorted({path.stat().st_size for path in saved}),
        "DownloadedSha256": sorted(downloaded_hashes),
        "HashVerified": downloaded_hashes == {EXPECTED_SHA256},
        "DynamicWorkerUsed": False,
        "Passed": True,
    }
    write_private(ROOT / "reports" / (candidate + "-pool-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-01")
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label is outside the owned fixture namespace")
    print(json.dumps(probe(CASES[args.version], args.candidate), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("static pool probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
