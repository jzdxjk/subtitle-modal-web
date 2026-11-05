# Subtitle Assistant 1.0.0.9 acceptance

The tagged Thunder query now uses `<code>.海南鸡字幕`, matching the prefix of uploaded subtitle names. The ordinary code query remains available for existing Thunder subtitles. This fixes the real WANZ-161 case where the ordinary code and tag-first queries did not return the uploaded file.

- Regression test failed before the query change and passed afterward.
- Release tests: 212 passed, 0 failed, 0 skipped.
- Release rebuild: 0 warnings and 0 errors.
- DLL SHA-256: `82017ed7abd97f477d4d5ba40aa806c9ce1362041c3e37ff112f237894aa8119`.
- All five isolated official Emby hosts (4.8.11.0, 4.9.1.80, 4.9.5.0, 4.10.0.40, 4.10.2.0) loaded this exact DLL and reported plugin/settings version 1.0.0.9.
- Native search on isolated Emby 4.10.2.0 returned six results including `[海南鸡字幕] WANZ-161.srt | 时长:01:58:01(字幕轴) | 大小:17.6 KB | 语言:中文`. This probe performed search only.
- Sanitized runtime reports remain under `/volume1/docker/emby-subtitle-assistant-validation-20261027/reports/candidate-15-*`.

Production installation used the hash-pinned staging helper and saved the previous DLL, configuration, and a consistent library database snapshot to `/volume1/docker/emby/backups/subtitle-assistant-20261029T025705Z-fb3a6d23`.

Production Emby restarted at 2026-10-29 10:57:15 Asia/Shanghai. The installed hash matches the tested artifact. Startup logs confirm version 1.0.0.9 loaded and the web, migration, cloud refresh, and automation entry points completed. The production container is running. The authenticated production search was not exercised; native WANZ-161 search was verified on the isolated host.
