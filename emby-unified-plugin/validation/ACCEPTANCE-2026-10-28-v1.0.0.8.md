# Subtitle Assistant 1.0.0.8 acceptance

## Result

The 1.0.0.8 candidate was installed on five isolated Emby versions and passed the native plugin/settings smoke check on each. The 4.10.2.0 host also returned the real Thunder search result for `SNOS-338` with the requested compact ChickenRice label. Its missing-subtitle task completed without downloading a second subtitle when the test media already had a Japanese `.jpn.srt` sidecar.

The production DLL was staged and Emby restarted. The container is running, the installed DLL hash matches the tested candidate, all Subtitle Assistant entry points completed startup, and the production settings page serves the ChickenRice note. The deployment backup includes the previous DLL and a SQLite library snapshot.

## Build and tests

- `dotnet test emby-unified-plugin.Tests/Emby.SubtitleAssistant.Tests.csproj --no-restore`: 211 passed, 0 failed.
- `dotnet build emby-unified-plugin/Emby.SubtitleAssistant.csproj --no-restore -c Release -t:Rebuild`: passed, 0 warnings and 0 errors.
- Validation harness tests: 11 run, 10 passed and 1 platform-specific test skipped.
- Deployment-stage tests: 31 passed.
- `python -m py_compile` passed for the updated runtime probes.
- Follow-up code review found no remaining blockers.

## Isolated Emby validation

All five hosts reported plugin and settings version `1.0.0.8`, the ChickenRice note, registered Local and Thunder providers, and the exact candidate DLL SHA-256 `f88e3795baf9b66ec842e69bdd545d41e547bb058679c479f44def1f819e5fd7`.

| Emby version | Plugin/settings smoke | ChickenRice priority note |
| --- | --- | --- |
| 4.8.11.0 | Passed | Passed |
| 4.9.1.80 | Passed | Passed |
| 4.9.5.0 | Passed | Passed |
| 4.10.0.40 | Passed | Passed |
| 4.10.2.0 | Passed | Passed |

On 4.10.2.0, native search returned 9 Thunder results, including:

```text
[海南鸡字幕] SNOS-338.srt | 时长:01:57:19(字幕轴) | 大小:58.3 KB | 语言:中文
```

No subtitle was downloaded during this manual search check. The existing-subtitle completion probe retained the single `IPX-697-CD2-1080p.jpn.srt` file and reported `ExistingAnyLanguageSubtitleSkipsDownload=true` after the scheduled task completed.

## Production deployment and rollback

- Installed DLL SHA-256: `f88e3795baf9b66ec842e69bdd545d41e547bb058679c479f44def1f819e5fd7`.
- Production container: `emby`, running after restart.
- Startup log: Subtitle Assistant web, migration, cloud refresh, and automation entry points all completed.
- Production settings resource: HTTP 200; contains `海南鸡字幕已上传至迅雷字幕库；搜索命中时优先展示海南鸡字幕。`
- Backup directory: `/volume1/docker/emby/backups/subtitle-assistant-20261028T143351Z-7d520bfa`.
- The backup contains the previous DLL, `stage.json`, and `library.snapshot.db`. No legacy plugin DLLs needed retirement.

The unauthenticated production `/Plugins` and `/SubtitleAssistant/settings` endpoints returned HTTP 401. The production DLL bytes match the candidate whose 1.0.0.8 version and native Thunder search were verified on the isolated hosts; no production authentication material was read or exported.
