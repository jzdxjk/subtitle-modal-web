# Subtitle Assistant 1.0.0.12 acceptance

Date: 2026-11-05

Candidate: `candidate-15`

Assembly, file and settings version: `1.0.0.12`

DLL SHA-256:
`2d9143eb648e330947834bc780bf18393473502696644169e718ebc766e5e9b5`

## Local verification

- .NET: 230 passed, 0 failed, 0 skipped.
- Worker: 29 passed, 0 failed.
- Python release/deployment and validation helpers: 42 passed, 1 POSIX-only
  check skipped on Windows.
- Release build: 0 warnings, 0 errors, one 267,776-byte DLL.

## Five-host matrix

The same DLL and settings version were verified on:

| Emby | Load | Tabs | Providers | Tasks | Admin settings | Built-in URL |
| --- | --- | --- | --- | --- | --- | --- |
| 4.8.11.0 | pass | 5 | 3 | 2 | pass | pass |
| 4.9.1.80 | pass | 5 | 3 | 2 | pass | pass |
| 4.9.5.0 | pass | 5 | 3 | 2 | pass | pass |
| 4.10.0.40 | pass | 5 | 3 | 2 | pass | pass |
| 4.10.2.0 | pass | 5 | 3 | 2 | pass | pass |

Unauthenticated access to the plugin settings API was rejected on every host.
The report files are `candidate-15-smoke-<version>.json`.

## Static-pool download

On Emby 4.10.2.0, saving a blank static-pool URL returned the built-in value:

```text
https://chickenrice-subtitle-static-00.jzdxjk.workers.dev
```

Native search for `GAREA-763` returned one `海南鸡字幕` result. Emby wrote two
language-suffixed copies; both were 67,612 bytes and both matched the signed
index SHA-256:

```text
4fcf99fe62563f6d699b6d9866127894730d79ee8b1d6b130ce20ba5d5f0febe
```

Evidence: `candidate-15-pool-4.10.2.0.json`.

## NAS production

- Emby 4.10.2.0 restarted successfully and loaded
  `Emby.SubtitleAssistant, Version=1.0.0.12`.
- The installed DLL SHA-256 matches the tested artifact.
- The existing manual static-pool URL was preserved.
- Backup:
  `/volume1/docker/emby/backups/subtitle-assistant-20261105T122627Z-52caeef0`
- The backup contains the previous 1.0.0.11 DLL, six configuration files, a
  quick-checked `library.snapshot.db`, and `stage.json`.
