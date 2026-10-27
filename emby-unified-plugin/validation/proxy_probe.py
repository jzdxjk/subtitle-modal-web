#!/usr/bin/env python3
"""Exercise the plugin's actual HTTP/SOCKS5 routing with private fixture traffic."""

import argparse
import json
import re
import sys
from urllib.request import urlopen

from emby_validation import CASES, ROOT, bootstrap, write_private


BASE = "http://172.17.0.1:19100"


def events():
    with urlopen(BASE + "/__test/events", timeout=5) as response:
        return json.load(response)


def proxy_events(transport):
    return len([event for event in events() if event.get("Proxy") == transport and event.get("TargetAllowed")])


def health_events():
    return len([event for event in events() if event.get("Path") == "/health" and not event.get("Proxy")])


def save(client, value):
    result = client.request("POST", "/SubtitleAssistant/settings", {"Proxy": value})
    if not result.get("Ok"):
        raise RuntimeError("could not save private proxy fixture settings")


def test_request(client, purpose):
    result = client.request("POST", "/SubtitleAssistant/proxy/test", {"Url": BASE + "/health", "Purpose": purpose})
    if client.last_status != 200 or not isinstance(result, dict):
        raise RuntimeError("proxy test API did not return HTTP 200 with a JSON object")
    return result


def probe(case, candidate):
    client = bootstrap(case)
    credentials = json.loads((ROOT / "mock-session.json").read_text())
    report = {"ServerVersion": case.version, "Candidate": candidate, "Transports": {}}
    try:
        for scheme, port, transport in [("http", 19101, "HTTP"), ("socks5", 19102, "SOCKS5")]:
            save(client, {
                "Enabled": True, "Address": scheme + "://172.17.0.1:" + str(port),
                "Username": credentials["Username"], "Password": credentials["Password"],
                "BypassLocal": False, "BypassHosts": "", "Thunder": True, "Pool": True,
                "Cloud": True, "Updates": True,
            })
            checks = {}
            for purpose in ["Thunder", "Pool", "Cloud", "Updates"]:
                before = proxy_events(transport)
                result = test_request(client, purpose)
                checks[purpose] = bool(result.get("Ok")) and proxy_events(transport) > before
            save(client, {"Pool": False})
            before = proxy_events(transport)
            checks["DisabledModuleUsesDirectRoute"] = bool(test_request(client, "Pool").get("Ok")) \
                and proxy_events(transport) == before
            before = proxy_events(transport)
            checks["PartialSaveKeepsProxyPassword"] = bool(test_request(client, "Thunder").get("Ok")) \
                and proxy_events(transport) > before
            report["Transports"][transport] = checks
        save(client, {"Address": "http://172.17.0.1:19103", "BypassLocal": False, "Pool": True})
        before = health_events()
        report["UnavailableProxyFailsWithoutDirectFallback"] = not test_request(client, "Thunder").get("Ok") \
            and health_events() == before
        save(client, {"BypassLocal": True})
        report["BypassLocalWorksWithUnavailableProxy"] = bool(test_request(client, "Pool").get("Ok"))
    finally:
        save(client, {"Enabled": False, "ClearPassword": True, "Username": "", "BypassLocal": True})
    report["Passed"] = all(value for checks in report["Transports"].values() for value in checks.values()) \
        and report["UnavailableProxyFailsWithoutDirectFallback"] and report["BypassLocalWorksWithUnavailableProxy"]
    write_private(ROOT / "reports" / (candidate + "-proxy-" + case.version + ".json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=list(CASES))
    parser.add_argument("--candidate", default="candidate-01")
    args = parser.parse_args()
    if not re.fullmatch(r"candidate-[0-9]+", args.candidate):
        raise ValueError("candidate label is outside the owned report namespace")
    report = probe(CASES[args.version], args.candidate)
    print(json.dumps(report, ensure_ascii=False))
    if not report["Passed"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("proxy probe failed: " + str(error), file=sys.stderr)
        sys.exit(1)
