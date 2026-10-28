#!/usr/bin/env python3
"""Report only booleans/statuses while probing native and plugin auth boundaries."""

import argparse
import json
import re
import secrets
import sys

from emby_validation import CASES, ROOT, EmbyClient, bootstrap, write_private
from plugin_smoke import PLUGIN_ID


def visible(value, values):
    if isinstance(value, dict):
        return any(visible(item, values) for item in value.values())
    if isinstance(value, list):
        return any(visible(item, values) for item in value)
    return isinstance(value, str) and any(secret in value for secret in values)


def attempt(client, method, path, secret_values, payload=None):
    try:
        value = client.request(method, path, payload)
        return {"Status": client.last_status, "Denied": False, "SecretFieldsVisible": visible(value, secret_values)}
    except RuntimeError as error:
        match = re.search(r"HTTP (\d+)", str(error))
        if not match:
            raise
        status = int(match[1])
        return {"Status": status, "Denied": status in (401, 403), "SecretFieldsVisible": False}


def probe(case, candidate):
    admin = bootstrap(case)
    path = ROOT / case.version / "session.json"
    state = json.loads(path.read_text())
    ordinary = state.get("OrdinaryUser")
    if not ordinary:
        user = admin.request("POST", "/Users/New", {"Name": "CodexValidationOrdinary"})
        authentication = EmbyClient(case).request("POST", "/Users/AuthenticateByName", {
            "Username": user["Name"], "Pw": "",
        })
        if authentication["User"].get("Policy", {}).get("IsAdministrator"):
            raise RuntimeError("the ordinary validation account unexpectedly has administrator privileges")
        ordinary = {"Name": user["Name"], "Id": user["Id"], "AccessToken": authentication["AccessToken"]}
        state["OrdinaryUser"] = ordinary
        write_private(path, state)
    user = EmbyClient(case, ordinary["AccessToken"])
    dummy_values = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
    result = admin.request("POST", "/SubtitleAssistant/settings", {
        "CloudApiToken": dummy_values[0], "Proxy": {"Enabled": False, "Password": dummy_values[1]},
    })
    if not result or not result.get("Ok"):
        raise RuntimeError("admin could not save temporary dummy secret fields")
    endpoints = [
        ("NativeConfiguration", "GET", "/Plugins/" + PLUGIN_ID + "/Configuration", None),
        ("PluginSettings", "GET", "/SubtitleAssistant/settings", None),
        ("CloudJobs", "GET", "/SubtitleAssistant/cloud/jobs", None),
        ("CloudSubmit", "POST", "/SubtitleAssistant/cloud/submit", {"ItemId": "invalid"}),
    ]
    report = {"ServerVersion": case.version, "Candidate": candidate, "OrdinaryUserIsAdministrator": False}
    try:
        report["Administrator"] = {
            label: attempt(admin, method, endpoint, dummy_values, payload)
            for label, method, endpoint, payload in endpoints
        }
        report["OrdinaryUser"] = {
            label: attempt(user, method, endpoint, dummy_values, payload)
            for label, method, endpoint, payload in endpoints
        }
        report["Unauthenticated"] = {
            label: attempt(EmbyClient(case), method, endpoint, dummy_values, payload)
            for label, method, endpoint, payload in endpoints
        }
    finally:
        admin.request("POST", "/SubtitleAssistant/settings", {
            "ClearCloudApiToken": True, "Proxy": {"ClearPassword": True, "Enabled": False},
        })
    report["NonAdminBoundariesPassed"] = all(
        item["Denied"] and not item["SecretFieldsVisible"]
        for role in ["OrdinaryUser", "Unauthenticated"] for item in report[role].values()
    )
    report["AdminCustomSettingsHideSecrets"] = not report["Administrator"]["PluginSettings"]["SecretFieldsVisible"]
    write_private(ROOT / "reports" / (candidate + "-auth-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-01")
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label is outside the owned report namespace")
    print(json.dumps(probe(CASES[args.version], args.candidate), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("auth probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
