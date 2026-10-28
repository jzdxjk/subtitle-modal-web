#!/usr/bin/env python3
"""Real native subtitle search/download against independent tiny fixtures."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid
from urllib.parse import quote, urlencode

from emby_validation import CASES, ROOT, bootstrap, library_items, write_private


def set_library_sources(client, enabled, order=None, languages=None):
    libraries = library_items(client.request("GET", "/Library/VirtualFolders/Query"))
    library = next(item for item in libraries if item["Locations"] == ["/media/videos"])
    options = library["LibraryOptions"]
    providers = client.request("GET", "/Libraries/AvailableOptions")["SubtitleFetchers"]
    names = [item["Name"] for item in providers]
    options.update({
        "DisabledSubtitleFetchers": [name for name in names if name not in enabled],
        "SubtitleFetcherOrder": order or ["本地字幕", "迅雷字幕"],
        "SubtitleDownloadLanguages": ["zh-CN"] if languages is None else languages,
        "RequirePerfectSubtitleMatch": False,
        "SaveSubtitlesWithMedia": True,
        "SampleIgnoreSize": 0,
        "SkipSubtitlesIfEmbeddedSubtitlesPresent": False,
        "SkipSubtitlesIfAudioTrackMatches": False,
    })
    client.request("POST", "/Library/VirtualFolders/LibraryOptions", {
        "Id": library["Id"], "LibraryOptions": options,
    })
    updated = next(item for item in library_items(client.request("GET", "/Library/VirtualFolders/Query"))
                   if item["Id"] == library["Id"])
    if updated["LibraryOptions"]["DisabledSubtitleFetchers"] != options["DisabledSubtitleFetchers"]:
        raise RuntimeError("native library did not persist provider enable switches")
    if updated["LibraryOptions"]["SubtitleFetcherOrder"] != options["SubtitleFetcherOrder"]:
        raise RuntimeError("native library did not persist custom provider order")
    return {"Enabled": enabled, "Disabled": options["DisabledSubtitleFetchers"], "Order": options["SubtitleFetcherOrder"]}


def movies(client):
    query = urlencode({"IncludeItemTypes": "Movie", "Recursive": "true", "Fields": "Path,MediaSources,MediaStreams,RunTimeTicks"})
    result = client.request("GET", "/Items?" + query)
    return result.get("Items", [])


def find_movie(client, path, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = [item for item in movies(client) if item.get("Path") == path]
        if found and found[0].get("RunTimeTicks", 0) > 0:
            return found[0]
        time.sleep(1)
    raise RuntimeError("tiny fixture was not scanned with video duration")


def copy_video(case, scenario, code="ABP-192", stem=None):
    root = ROOT / case.version / "media"
    directory = root / "videos" / scenario
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / ((stem or code + "-CD2-1080p") + ".mp4")
    if not target.exists():
        source = root / "videos" / "ABP-192-CD2-1080p.mp4"
        shutil.copyfile(source, target)
    return target, "/media/videos/" + scenario + "/" + target.name


def manual(case, candidate, stem="ABP-192-CD2-1080p"):
    client = bootstrap(case)
    root = ROOT / case.version / "media"
    subtitle_root = root / "subtitles"
    subtitle_root.mkdir(mode=0o700, exist_ok=True)
    if stem.startswith("SSIS-157"):
        code = "SSIS-157"
    elif stem.startswith("abc-123"):
        code = "ABC-123"
    else:
        code = "ABP-192"
    subtitle = subtitle_root / (code + ".fixture.srt")
    shutil.copyfile(root / "subtitle-fixtures/ABP-192.fixture.srt", subtitle)
    configured = client.request("POST", "/SubtitleAssistant/settings", {
        "LocalPaths": "/media/subtitles", "LocalMaxResults": 5,
        "ThunderMaxResults": 10,
        "AutoDownloadOnNewMedia": False,
        "Proxy": {"Enabled": True, "Address": "http://172.17.0.1:19101", "Thunder": True,
                  "Cloud": False, "Updates": False, "BypassLocal": False},
    })
    if not configured.get("Ok"):
        raise RuntimeError("could not configure local fixture paths")
    sources = set_library_sources(client, ["本地字幕"], languages=[])
    video, path = copy_video(case, "manual-" + candidate + "-" + uuid.uuid4().hex[:8], code=code, stem=stem)
    client.request("POST", "/Library/Refresh", {})
    item = find_movie(client, path)
    media_source = next(source for source in item["MediaSources"] if source["Path"] == path)
    query = urlencode({"MediaSourceId": media_source["Id"], "IsPerfectMatch": "false"})
    results = client.request("GET", "/Items/" + item["Id"] + "/RemoteSearch/Subtitles/zh-CN?" + query)
    selected = [result for result in results if result.get("ProviderName") == "本地字幕"]
    if len(selected) != 1:
        raise RuntimeError("native manual search did not return the local fixture exactly once")
    client.request("POST", "/Items/" + item["Id"] + "/RemoteSearch/Subtitles/" + quote(selected[0]["Id"], safe="")
                   + "?" + urlencode({"MediaSourceId": media_source["Id"]}), {})
    deadline = time.monotonic() + 25
    external = []
    while time.monotonic() < deadline:
        updated = next(movie for movie in movies(client) if movie.get("Path") == path)
        external = [stream for stream in updated.get("MediaStreams", [])
                    if stream.get("Type") == "Subtitle" and stream.get("IsExternal")]
        if external:
            break
        time.sleep(1)
    saved = list(video.parent.glob(video.stem + ".*.srt"))
    content_equal = len(saved) == 1 and saved[0].read_bytes() == subtitle.read_bytes()
    report = {
        "ServerVersion": case.version, "Candidate": candidate, "Scenario": "NativeLocalManualDownload",
        "NativeLibrarySources": sources, "NativeSearchResults": len(results),
        "NativeLocalResults": len(selected),
        "NativeManualSearchIncludesOtherProviders": any(result.get("ProviderName") != "本地字幕" for result in results),
        "NativeProviderPrefix": selected[0]["Id"].split("_", 1)[0],
        "VideoStem": video.stem, "RunTimeTicks": item.get("RunTimeTicks"),
        "SavedSubtitleNames": [path.name for path in saved],
        "CompleteStemPreserved": len(saved) == 1 and saved[0].name.startswith(video.stem + "."),
        "NativeLanguageSuffixPreserved": len(saved) == 1 and saved[0].name == video.stem + ".zh-CN.srt",
        "OriginalBytesPreserved": content_equal,
        "ExternalStreamsVisibleWithoutFullRescan": bool(external),
        "ExternalSubtitleLanguages": [stream.get("Language") for stream in external],
    }
    report["Passed"] = report["CompleteStemPreserved"] and report["NativeLanguageSuffixPreserved"] and content_equal and bool(external)
    write_private(ROOT / "reports" / (candidate + "-manual-" + code.lower() + "-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-01")
    parser.add_argument("--stem", choices=[
        "ABP-192-CD2-1080p", "SSIS-157-c-无码破解",
        "abc-123-4k", "abc-123-无码破解", "abc-123-4k-无码破解",
    ], default="ABP-192-CD2-1080p")
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label is outside the owned fixture namespace")
    report = manual(CASES[args.version], args.candidate, args.stem)
    print(json.dumps(report, ensure_ascii=False))
    if not report["Passed"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("business probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
