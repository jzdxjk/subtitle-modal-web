# Subtitle Assistant 1.0.0.10 acceptance

This release stops routine Emby caller cancellation from being propagated as an
error while preserving shared Thunder work for other callers.

## Release identity

- Source commit: `69b68107`
- Version release:
  `https://github.com/jzdxjk/subtitle-modal-web/releases/tag/emby-subtitle-assistant-v1.0.0.10`
- DLL SHA-256:
  `658351db43c6be5833b02d282b2ccb097b17e6e42585e00f4a765702186c3d7c`
- DLL size: 251392 bytes
- Stable update pointer:
  `https://github.com/jzdxjk/subtitle-modal-web/releases/download/emby-subtitle-assistant-update/update.json`

The published version release contains `Emby.SubtitleAssistant.dll`, `update.json`,
and `SHA256SUMS.txt`. The mutable update-pointer release contains the matching
`update.json`; both manifest assets have SHA-256
`8261ae3e7df3a919cfb94242cb2c903a8af3d175289cd8943adb0a368c99e609`.

## Pre-production verification

- Plugin tests: 213 passed, 0 failed, 0 skipped.
- GitHub release helper tests: 22 passed.
- Validation harness tests: 7 passed, 1 skipped because the local Windows host is
  not POSIX.
- Five isolated official Emby hosts loaded this exact DLL:
  - 4.8.11.0
  - 4.9.1.80
  - 4.9.5.0
  - 4.10.0.40
  - 4.10.2.0
- Every host reported plugin/settings version 1.0.0.10, the tested SHA-256, both
  subtitle providers, and both Subtitle Assistant scheduled tasks.

## Production scheduled update

Production Emby 4.10.2.0 ran the native `SubtitleAssistantUpdate` task from the
installed 1.0.0.9 plugin. The task completed successfully in 2.22 seconds and
atomically replaced the plugin with the published 1.0.0.10 DLL.

- Backup retained:
  `/volume1/docker/emby/config/plugins/.subtitle-assistant-update/Emby.SubtitleAssistant-1.0.0.9-20261031022138-279ec524a4bb4d199862ad7b50a61ee0.bak`
- New DLL SHA-256 before restart:
  `658351db43c6be5833b02d282b2ccb097b17e6e42585e00f4a765702186c3d7c`
- No temporary candidate remained after installation.
- Emby was restarted only after confirming zero active playback sessions.

## Production runtime acceptance

After restart:

- Emby reports plugin and settings version 1.0.0.10.
- The running DLL hash is the tested SHA-256 above.
- `HasPendingRestart` is false.
- `SubtitleAssistantUpdate` and `SubtitleAssistantMissingSubtitles` are idle with
  completed last results.
- A search-only native request for `WANZ-161` returned six Thunder subtitles.
- The first result is
  `[海南鸡字幕] WANZ-161.srt | 时长:01:58:01(字幕轴) | 大小:17.6 KB | 语言:中文`.
- No new `Error searching for subtitles on 迅雷字幕` or
  `OperationCanceledException` entry appeared after the acceptance search.
