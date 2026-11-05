# Subtitle Assistant 1.0.0.7 acceptance

## Result

The revised `Emby.SubtitleAssistant` plugin was installed and restarted on the production Emby server. Production startup loaded version `1.0.0.7`, logged successful legacy/library-source migration, and Emby reports version `4.10.2.0`.

The active plugin configuration now has `MigrationVersion=2`, `ThunderMaxResults=10`, and provider order `Local, Thunder`. The retired pool fields are absent from the active XML configuration. Local result count remains 5. The isolated migration probe confirmed that other provider keys, disabled sources, cloud settings, and unrelated library flags remain intact.

## Build and tests

- `dotnet build emby-unified-plugin/Emby.SubtitleAssistant.csproj -c Release --no-restore`: passed, 0 warnings and 0 errors.
- `dotnet test emby-unified-plugin.Tests/Emby.SubtitleAssistant.Tests.csproj -c Release --no-restore`: 195 passed, 0 failed.
- Validation Python suite: 11 tests, 10 passed and 1 skipped; `compileall` and `git diff --check` passed.
- Thunder behavior is covered with controlled HTTP responses: ordinary and tagged queries, tagged-query failure fallback, exact code/format filtering, matching-language ChickenRice priority, unknown-language non-priority, duplicate fallback URLs, 10-result manual limit, and complete automation candidates. No live production Thunder query or subtitle download was made.
- Legacy limits of 5 and values above 10 are normalized to 10 in both version-0 import and version-1 upgrade paths before validation.

## Isolated Emby validation

The final DLL SHA256 (`039d67a46f220dedecd4b38cf002ae1c1dfc3aebcccd8f44f352e390e53dcf68`) was installed in all five isolated Emby versions. Each smoke check confirmed four settings tabs, one Local provider, one Thunder provider, no retired pool provider, Thunder limit 10, and successful plugin/API registration.

| Emby version | Native manual subtitle save | Video stem |
| --- | --- | --- |
| 4.8.11.0 | Passed | `abc-123-4k` |
| 4.9.1.80 | Passed | `abc-123-无码破解` |
| 4.9.5.0 | Passed | `abc-123-4k-无码破解` |
| 4.10.0.40 | Passed | `ABP-192-CD2-1080p` |
| 4.10.2.0 | Passed | `abc-123-4k-无码破解` |

For these native saves, the full video stem and subtitle bytes were preserved, and each subtitle became visible without a full-library rescan. Emby used its native language suffix (`zh-CN` for manual saves; `zh` in the 4.10.2 automation fixture).

On 4.10.2, both new-item automation and the missing-subtitle backfill task passed. They preserved the full stem and bytes, refreshed only the item, skipped rewriting an existing Chinese subtitle, and used the host's native `.zh.srt` naming. The new-item probe observed the configured 60-second delay.

The 4.10.2 migration probe passed both upgrade rounds and confirmed backups and user edits survive restart. The provider-order probe confirmed the default Local-first order and that an administrator's Thunder-first order takes effect after Emby restart.

Candidate reports are in `reports/candidate-14-*.json` (14 sanitized reports).

## Production deployment and rollback record

- Installed DLL SHA256: `039d67a46f220dedecd4b38cf002ae1c1dfc3aebcccd8f44f352e390e53dcf68`.
- Production restart: completed; container is running and logs show plugin `1.0.0.7` plus successful settings/library migration.
- Backup directory: `/volume1/docker/emby/backups/subtitle-assistant-20261028T131637Z-816a0caa`.
- The backup contains the previous DLL (SHA256 `cca48edcc1477b969217829c138d1f97c499cb2376155e57c84b5667693dd006`), the prior plugin and legacy configuration files, a `stage.json`, and a 96,722,944-byte SQLite library snapshot.
- Only `Emby.SubtitleAssistant` was staged. No retired standalone plugin DLLs were present to remove.
