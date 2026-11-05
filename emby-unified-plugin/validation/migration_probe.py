#!/usr/bin/env python3
"""Exercise real startup migration and native CollectionFolder option writes."""

import argparse
import json
import os
import re
import secrets
import sys
import xml.etree.ElementTree as ET

from emby_validation import CASES, ROOT, bootstrap, library_items, start, stop, write_private
from plugin_smoke import PLUGIN_ID


OLD_ORDER = ["MeiamSub.LocalPool", "Open Subtitles", "海南鸡字幕池", "MeiamSub.Thunder", "ThunderSubtitle"]
NEW_ORDER = ["本地字幕", "Open Subtitles", "迅雷字幕"]
BASE = "http://172.17.0.1:19100"


def write_bytes(path, data):
    temporary = path.with_name(path.name + ".qa-new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    path.chmod(0o600)


def library(client):
    return next(item for item in library_items(client.request("GET", "/Library/VirtualFolders/Query"))
                if item.get("Locations") == ["/media/videos"])


def configure_old_keys(client, disabled):
    info = library(client)
    options = info["LibraryOptions"]
    options.update({"SubtitleFetcherOrder": OLD_ORDER, "DisabledSubtitleFetchers": disabled,
                    "SkipSubtitlesIfAudioTrackMatches": True, "SaveSubtitlesWithMedia": False})
    client.request("POST", "/Library/VirtualFolders/LibraryOptions", {"Id": info["Id"], "LibraryOptions": options})
    saved = library(client)["LibraryOptions"]
    if saved["SubtitleFetcherOrder"] != OLD_ORDER or saved["DisabledSubtitleFetchers"] != disabled:
        raise RuntimeError("native host did not retain the legacy migration fixture keys")


def prepare_v1_config(config, local_paths, auto_download, cloud_url, cloud_token, cloud_mappings):
    tree = ET.fromstring(config.read_bytes())
    namespace = tree.tag.split("}", 1)[0] + "}" if "}" in tree.tag else ""
    def child(name):
        return next((item for item in tree if item.tag.rsplit("}", 1)[-1] == name), None)
    marker = child("MigrationVersion")
    if marker is None:
        marker = ET.SubElement(tree, namespace + "MigrationVersion")
    marker.text = "1"
    values = {
        "LocalPaths": local_paths,
        "AutoDownloadOnNewMedia": "true" if auto_download else "false",
        "CloudServiceUrl": cloud_url,
        "CloudApiToken": cloud_token,
        "CloudPathMappings": cloud_mappings,
    }
    for name, value in values.items():
        element = child(name)
        if element is None:
            element = ET.SubElement(tree, namespace + name)
        element.text = value
    limit = child("ThunderMaxResults")
    if limit is None:
        limit = ET.SubElement(tree, namespace + "ThunderMaxResults")
    limit.text = "5"
    order = child("ProviderDisplayOrder")
    if order is None:
        order = ET.SubElement(tree, namespace + "ProviderDisplayOrder")
    for item in list(order):
        order.remove(item)
    for key in ["Pool", "Thunder", "Local"]:
        ET.SubElement(order, namespace + "string").text = key
    write_bytes(config, ET.tostring(tree, encoding="utf-8", xml_declaration=True))


def lock_secret_test_files(directory):
    for path in directory.rglob("*"):
        if path.is_file():
            path.chmod(0o600)


def probe(case, candidate):
    client = bootstrap(case)
    directory = ROOT / case.version / "config/plugins/configurations"
    config = directory / "Emby.SubtitleAssistant.xml"
    if not config.is_file():
        raise RuntimeError("unified configuration file does not exist in this owned host")
    original_xml = config.read_bytes()
    original_library = library(client)
    state_path = ROOT / case.version / "migration-qa-original.json"
    write_private(state_path, {"Library": original_library})
    write_bytes(ROOT / case.version / "migration-qa-original.xml", original_xml)
    report = {"ServerVersion": case.version, "Candidate": candidate, "Rounds": []}
    try:
        rounds = [
            ("retired-pool-auto-or-and-all-disabled", False, True, False, False,
             ["MeiamSub.LocalPool", "ThunderSubtitle", "海南鸡字幕池", "MeiamSub.Thunder"],
             ["本地字幕", "迅雷字幕"]),
            ("extra-thunder-is-ignored-and-one-disabled", False, False, True, True,
             ["ThunderSubtitle", "MeiamSub.Thunder"], ["迅雷字幕"]),
        ]
        for label, thunder_auto, pool_auto, extra_auto, existing_auto, old_disabled, expected_disabled in rounds:
            configure_old_keys(client, old_disabled)
            stop(case)
            token = secrets.token_urlsafe(28)
            current_local_paths = "/media/v1-choice-subtitles"
            current_cloud_url = "https://v1-config.invalid/service"
            current_cloud_token = secrets.token_urlsafe(28)
            current_cloud_mappings = "/media=/v1-config"
            write_private(directory / "MeiamSub.LocalPool.json", {"SubtitleLibraryPaths": "/media/migration-imported-subtitles"})
            write_private(directory / "ThunderSubtitle.json", {"EnableAutoDownloadOnNewMedia": thunder_auto})
            write_private(directory / "ChickenRicePool.json", {
                "PoolBaseUrl": BASE + "/pool/manual", "RequestTimeoutSeconds": 17,
                "EnableAutoDownloadOnNewMedia": pool_auto,
                "SimplifiedChineseLanguage": "zh-CN", "TraditionalChineseLanguage": "zh-TW",
            })
            write_private(directory / "MeiamSub.Thunder.json", {"EnableAutoDownloadOnNewMedia": extra_auto,
                                                                     "ThunderMaxResults": 9999})
            cloud = ET.Element("PluginConfiguration")
            values = {"ServiceUrl": BASE + "/cloud/" + case.version, "ApiToken": token,
                      "PathMappings": "/legacy/source=/migration/fixture"}
            for name, value in values.items():
                ET.SubElement(cloud, name).text = value
            write_bytes(directory / "SubtitleCloudPlugin.xml", ET.tostring(cloud, encoding="utf-8", xml_declaration=True))
            prepare_v1_config(config, current_local_paths, existing_auto, current_cloud_url,
                              current_cloud_token, current_cloud_mappings)
            start(case)
            client = bootstrap(case)
            native = client.request("GET", "/Plugins/" + PLUGIN_ID + "/Configuration")
            options = library(client)["LibraryOptions"]
            result = {
                "Case": label, "MigrationVersion": native.get("MigrationVersion"),
                "LocalPathsPreserved": native.get("LocalPaths") == current_local_paths,
                "CloudConnectionPreserved": native.get("CloudServiceUrl") == current_cloud_url,
                "CloudTokenPreserved": native.get("CloudApiToken") == current_cloud_token,
                "CloudMappingsPreserved": native.get("CloudPathMappings") == current_cloud_mappings,
                "RetiredPoolSettingsAbsent": "PoolUrl" not in native and "PoolTimeoutSeconds" not in native
                    and "PoolMaxResults" not in native and "Pool" not in native.get("Proxy", {}),
                "OldThunderDisplayLimitRaised": native.get("ThunderMaxResults") == 10,
                "ProviderOrderProjected": native.get("ProviderDisplayOrder") == ["Thunder", "Local"],
                "AutoDownloadSettingPreserved": native.get("AutoDownloadOnNewMedia") == existing_auto,
                "ExtraThunderDoesNotOverwriteDisplayLimit": native.get("ThunderMaxResults") != 9999,
                "NativeOrder": options.get("SubtitleFetcherOrder"),
                "NativeDisabled": options.get("DisabledSubtitleFetchers"),
                "OrderMappedAndUnknownProviderPreserved": options.get("SubtitleFetcherOrder") == NEW_ORDER,
                "DisabledMappedWithoutReenabling": options.get("DisabledSubtitleFetchers") == expected_disabled,
                "UnrelatedFlagsPreserved": options.get("SkipSubtitlesIfAudioTrackMatches") is True
                    and options.get("SaveSubtitlesWithMedia") is False,
                "PendingMarkerRemoved": not (directory / "subtitle-assistant-migration.pending").exists(),
                "ServerBackupsRetained": bool(list((directory / "subtitle-assistant-migration-backups").glob("*/new-config.original"))),
            }
            result["Passed"] = result["MigrationVersion"] == 2 and all(value for key, value in result.items()
                if isinstance(value, bool))
            report["Rounds"].append(result)
            lock_secret_test_files(directory)
            if not result["Passed"]:
                raise RuntimeError("real startup migration failed a field, native library or completion-marker assertion")
        user_update = {"LocalPaths": "/media/user-choice-subtitles", "LocalMaxResults": 9,
                       "AutoDownloadOnNewMedia": True, "CloudServiceUrl": "", "ClearCloudApiToken": True}
        if not client.request("POST", "/SubtitleAssistant/settings", user_update).get("Ok"):
            raise RuntimeError("could not save user overrides after migration")
        stop(case)
        start(case)
        client = bootstrap(case)
        native = client.request("GET", "/Plugins/" + PLUGIN_ID + "/Configuration")
        report["LegacyFilesRemain"] = all((directory / name).is_file() for name in [
            "MeiamSub.LocalPool.json", "ThunderSubtitle.json", "ChickenRicePool.json", "SubtitleCloudPlugin.xml", "MeiamSub.Thunder.json"])
        report["UserOverridesSurviveRestartWithoutReimport"] = native.get("MigrationVersion") == 2 \
            and native.get("LocalMaxResults") == 9 and native.get("LocalPaths") == user_update["LocalPaths"] \
            and native.get("AutoDownloadOnNewMedia") is True and native.get("CloudServiceUrl") == "" \
            and not native.get("CloudApiToken")
        report["Passed"] = all(item["Passed"] for item in report["Rounds"]) \
            and report["LegacyFilesRemain"] and report["UserOverridesSurviveRestartWithoutReimport"]
    finally:
        try:
            lock_secret_test_files(directory)
            stop(case)
            write_bytes(config, original_xml)
            start(case)
            client = bootstrap(case)
            client.request("POST", "/Library/VirtualFolders/LibraryOptions", {
                "Id": original_library["Id"], "LibraryOptions": original_library["LibraryOptions"],
            })
            report["OriginalQaSettingsRestored"] = True
        except Exception as error:
            report["OriginalQaSettingsRestored"] = False
            report["RestoreFailureType"] = type(error).__name__
            report["Passed"] = False
        finally:
            write_private(ROOT / "reports" / (candidate + "-migration-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-03")
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label is outside the owned report namespace")
    start(CASES[args.version])
    report = probe(CASES[args.version], args.candidate)
    print(json.dumps(report, ensure_ascii=False))
    if not report["Passed"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("migration probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
