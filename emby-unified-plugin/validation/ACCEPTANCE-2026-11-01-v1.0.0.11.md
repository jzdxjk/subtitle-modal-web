# Subtitle Assistant 1.0.0.11 acceptance

## Build identity

- Assembly, file and settings version: `1.0.0.11`
- SHA-256:
  `0970366217a361e34540e0ee64337abbaaa9206a63534c2738efed1934ed3668`
- Release build: 0 warnings, 0 errors

## Automated verification

- .NET: 223 passed, 0 failed, 0 skipped
- Python helpers: 41 passed, 1 skipped
- The skipped POSIX permission check was rerun on the NAS validation host.

## Runtime smoke

The exact SHA-256 above was installed into the isolated official Emby
`4.10.2.0` host. The host reported:

- plugin version `1.0.0.11`
- settings version `1.0.0.11`
- five configuration tabs
- one registration each for 海南鸡字幕, 本地字幕 and 迅雷字幕
- both Subtitle Assistant scheduled tasks
- static pool endpoint unset until explicit cutover
- authenticated settings API available
- unauthenticated settings API denied

Earlier static-provider candidates passed plugin-loading smoke on official Emby
`4.8.11.0`, `4.9.1.80`, `4.9.5.0`, `4.10.0.40` and `4.10.2.0`.
