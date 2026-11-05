# Isolated Emby runtime validation

The driver runs on NAS as root through the existing Windows Credential Manager
helper. It accepts only these official `emby/embyserver` images and owned
containers:

| Server | Container | Host binding |
| --- | --- | --- |
| 4.8.11.0 | codex-subtitle-assistant-4811 | 127.0.0.1:19048 |
| 4.9.1.80 | codex-subtitle-assistant-49180 | 127.0.0.1:19049 |
| 4.9.5.0 | codex-subtitle-assistant-495 | 127.0.0.1:19059 |
| 4.10.0.40 | codex-subtitle-assistant-410040 | 127.0.0.1:19040 |
| 4.10.2.0 | codex-subtitle-assistant-4102 | 127.0.0.1:19042 |

Each container has one CPU and 1 GiB RAM. The driver refuses to start a third
running validation container. It verifies the task label, image, exact two
mounts, limits and loopback binding before reusing or stopping a container.
There is no delete-directory command.

On this NAS, UGOS projects the task-private bind directories as mode 111 to
non-root container users even when the NAS root view reports mode 777. A direct
UID 2 and UID 1001 write probe failed; the otherwise-identical UID 0 probe
succeeded. Plugin validation therefore runs the official image with explicit
`UID=0`, `GID=0`, `GIDLIST=0`, without privileged mode, devices, Docker socket or
production mounts. Installing a candidate replaces an older stopped validation
container if necessary, retaining its independent config/media bind paths.

All NAS files live under the new task-marked directory:

```text
/volume1/docker/emby-subtitle-assistant-validation-20261027/
  task-marker.txt
  scripts/               public copies of this driver and its tests
  images/                official image pull logs and digest evidence
  reports/               sanitized runtime reports
  VERSION/config/        independent stock Emby configuration
  VERSION/media/videos/  generated 12-second black video, about 1.5 KiB
  VERSION/media/subtitle-fixtures/ independent Chinese SRT fixture
  VERSION/session.json   generated validation credentials, mode 0600
```

The startup wizard creates a dedicated validation administrator. Passwords and
tokens are generated on NAS, kept in the private session file, sent in HTTP
bodies/headers, and excluded from console output and project files. Never copy
`session.json` or the Emby config directories into this repository.

## Local checks

```powershell
python -m unittest discover -s . -p test_harness.py
```

The POSIX permission check additionally runs on NAS. The tests cover refusal of
production container names/mounts, public ports, version/path escape and HTTP
failure messages leaking credentials. A startup connection reset is retried
while the isolated server initializes.

## Sync the public driver

From this directory, the following only writes the two public scripts under
the already-created, task-marked NAS directory. It does not copy credentials.

```powershell
$validationDirectory = (Get-Location).Path
foreach ($scriptName in @('emby_validation.py', 'test_harness.py')) {
    $encodedScript = [Convert]::ToBase64String(
        [IO.File]::ReadAllBytes((Join-Path $validationDirectory $scriptName)))
    $remoteCommand = 'set -eu; task_root=/volume1/docker/emby-subtitle-assistant-validation-20261027; ' +
        'grep -qx "task=subtitle-assistant-validation-20261027" "$task_root/task-marker.txt"; umask 077; ' +
        "printf '%s' '$encodedScript' | base64 -d > " + '"$task_root/scripts/' + $scriptName + '"; ' +
        'chmod 700 "$task_root/scripts/' + $scriptName + '"'
    & 'C:\Users\jzdxjk\.codex\nas-sudo.ps1' -Command $remoteCommand
    if ($LASTEXITCODE -ne 0) { throw 'Validation script sync failed' }
}
```

## Start, bootstrap, stop

The official images must already have been pulled. `baseline` starts the
selected host, verifies its reported server version, uses the real startup
wizard, authenticates the dedicated administrator, creates only the dedicated
`/media/videos` library, generates the tiny video/SRT, and saves a sanitized
report. Existing sessions are reused. Baseline reports describe stock hosts;
they do not claim the combined plugin has passed runtime acceptance.

```powershell
& 'C:\Users\jzdxjk\.codex\nas-sudo.ps1' -Command '
set -eu
task_root=/volume1/docker/emby-subtitle-assistant-validation-20261027
TMPDIR="$task_root/tmp" python3 -m unittest discover -s "$task_root/scripts" -p test_harness.py
python3 "$task_root/scripts/emby_validation.py" baseline 4.8.11.0
python3 "$task_root/scripts/emby_validation.py" stop 4.8.11.0
'
```

Replace the version with another row from the table. Stop only an owned
validation case when two cases already run. No command in this driver stops or
changes the production `emby` container.

Official API references used for the live startup/library session:
[authentication](https://dev.emby.media/reference/RestAPI/UserService/postUsersAuthenticatebyname.html),
[dedicated media library](https://dev.emby.media/reference/RestAPI/LibraryStructureService/postLibraryVirtualfolders.html).
