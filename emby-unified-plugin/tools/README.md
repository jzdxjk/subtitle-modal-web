# GitHub release helper

This standard-library script is restricted to `jzdxjk/subtitle-modal-web`.
The authoring agent ran only the public check. An authorized operator must run
authentication, publishing, or PR creation after the five-host acceptance checks.

Run from the repository root in PowerShell:

```powershell
python -m unittest discover -s emby-unified-plugin/tools -p test_github_release.py -q
python emby-unified-plugin/tools/github_release.py --check-public
python emby-unified-plugin/tools/github_release.py --check-auth

$releaseCommit = git rev-parse HEAD
python emby-unified-plugin/tools/github_release.py --publish `
  --dll emby-unified-plugin/bin/Release/netstandard2.1/Emby.SubtitleAssistant.dll `
  --version 1.0.0.0 --commit $releaseCommit --body-file release-notes.md

python emby-unified-plugin/tools/github_release.py --create-pr `
  --head codex/subtitle-assistant --base dev --body-file pr-description.md
```

`--check-public` never reads credentials. Other modes capture an existing
`GH_TOKEN` or `gh auth token --hostname github.com` in memory. Only a real HTTP
401 permits one fallback to the existing Windows Git Credential Manager, with
interactive prompts disabled. No credential, response body, or response header is
printed or written to disk. The helper does not push branches, log in, reset
credentials, or change machine/router/DNS/proxy settings.

The API transport resolves real public A records through verified Cloudflare
HTTPS DNS, with Google HTTPS DNS as fallback, and caches them only in this
process. It uses `API.GITHUB.COM` as TLS SNI to avoid the observed local network
failure, while the HTTP host remains `api.github.com`. Both API and uploads use
the default trusted CA context with required certificate and hostname checks.
Requests never follow redirects. Credentials are sent only to the two GitHub
hosts and the repository-specific endpoint allowlist.

Publishing prepares a draft at the exact supplied commit, verifies and uploads
`Emby.SubtitleAssistant.dll`, `update.json`, and `SHA256SUMS.txt`, then publishes
with `make_latest=false`. Existing assets require matching SHA256 metadata;
missing/different digests cause refusal, and version assets are never replaced or
deleted. The version and DLL must already have passed release validation.

The separate `emby-subtitle-assistant-update` release contains the mutable
`update.json` pointer. Its replacement is uploaded and verified under a
deterministic temporary name before the old pointer is deleted and the verified
asset renamed. If interrupted between deletion and rename, rerunning the same
version resumes from the verified temporary asset. A failure does not delete any
version release or version asset. An existing open PR for the fixed head/base is
returned instead of creating a duplicate; a new PR is a draft.

API contracts: [releases](https://docs.github.com/en/rest/releases/releases),
[release assets](https://docs.github.com/en/rest/releases/assets), and
[pull requests](https://docs.github.com/en/rest/pulls/pulls).
