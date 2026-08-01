import os
import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import AppConfig, ConfigStore
from app.media import (
    build_ffmpeg_command,
    discover_media,
    extract_av_code,
    is_video_file,
    list_small_av_files,
    normalize_av_code,
    output_subtitle_path,
    prepare_audio,
)
from app.modal_runner import (
    ModalRunHandle,
    ModalRunner,
    is_transient_modal_connection_error,
    modal_client_wait_timeout,
)
from app.storage import JobStore
from app.worker import JobRunner, SmallFileIgnoreStore


def test_modal_credentials_only_use_webui_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"modal_token_id":"file-id","default_gpu":"A10G"}', encoding="utf-8")
    monkeypatch.setenv("MODAL_TOKEN_ID", "env-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "env-secret")

    config = ConfigStore(config_path).load()

    assert config.modal_token_id == "file-id"
    assert config.modal_token_secret == ""
    assert config.default_gpu == "A10G"
    assert config.redacted()["modal_token_id"] == "fil***-id"
    assert config.redacted()["modal_token_secret"] == ""


def test_config_defaults_include_min_file_size_mb():
    config = AppConfig()

    assert config.min_file_size_mb == 100
    assert config.repo_branch == "v1.10"


def test_config_migrates_legacy_modal_credentials_to_a_default_account(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.path.write_text('{"modal_token_id":"legacy-id","modal_token_secret":"legacy-secret"}', encoding="utf-8")

    config = store.load()

    assert config.active_modal_account_id == "default"
    assert config.modal_accounts[0]["name"] == "默认账户"
    assert config.modal_accounts[0]["token_id"] == "legacy-id"


def test_jobs_remember_the_modal_account_and_block_its_deletion(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False, modal_account_id="account-a")
    store.create_job("/watch/legacy.mp4", "/output", ["srt"], False)

    assert job.modal_account_id == "account-a"
    assert store.has_active_jobs_for_modal_account("account-a") is True
    assert store.has_active_jobs_for_modal_account("default") is True


def test_jobs_persist_input_size_bytes(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")

    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False, input_size_bytes=1420000000)

    assert job.input_size_bytes == 1420000000
    assert store.get_job(job.id).input_size_bytes == 1420000000


def test_job_store_backfills_size_for_legacy_jobs_when_media_still_exists(tmp_path):
    media = tmp_path / "SEVEN-035.mp4"
    media.write_bytes(b"x" * 4096)
    database = tmp_path / "jobs.sqlite3"
    store = JobStore(database)
    job = store.create_job(str(media), "/output", ["srt"], False, input_size_bytes=0)

    reloaded = JobStore(database).get_job(job.id)

    assert reloaded.input_size_bytes == 4096


def test_job_store_backfills_size_from_move_target_for_completed_legacy_jobs(tmp_path):
    moved = tmp_path / "done"
    moved.mkdir()
    media = moved / "SEVEN-035.mp4"
    media.write_bytes(b"x" * 8192)
    database = tmp_path / "jobs.sqlite3"
    store = JobStore(database)
    job = store.create_job(
        str(tmp_path / "watch" / media.name),
        "/output",
        ["srt"],
        False,
        move_target_dir=str(moved),
        input_size_bytes=0,
    )

    reloaded = JobStore(database).get_job(job.id)

    assert reloaded.input_size_bytes == 8192


def test_job_store_backfills_size_from_default_move_target_for_legacy_jobs(tmp_path):
    moved = tmp_path / "done" / "HAWA-375"
    moved.mkdir(parents=True)
    media = moved / "HAWA-375.mp4"
    media.write_bytes(b"x" * 8192)
    database = tmp_path / "jobs.sqlite3"
    source = tmp_path / "watch" / "HAWA-375"
    store = JobStore(database)
    job = store.create_job(
        str(source),
        "/output",
        ["srt"],
        False,
        input_size_bytes=0,
    )

    reloaded = JobStore(
        database,
        default_move_target_dir=str(tmp_path / "done"),
    ).get_job(job.id)

    assert reloaded.input_size_bytes == 8192


def test_job_store_records_total_media_size_for_directory_jobs(tmp_path):
    media_dir = tmp_path / "HAWA-375"
    media_dir.mkdir()
    (media_dir / "HAWA-375.mp4").write_bytes(b"x" * 4096)
    (media_dir / "poster.jpg").write_bytes(b"x" * 1024)

    job = JobStore(tmp_path / "jobs.sqlite3").create_job(
        str(media_dir), "/output", ["srt"], False
    )

    assert job.input_size_bytes == 4096


def test_job_store_excludes_media_below_configured_size_threshold(tmp_path):
    media_dir = tmp_path / "HAWA-375"
    media_dir.mkdir()
    large = media_dir / "HAWA-375.mp4"
    small = media_dir / "HAWA-375-preview.mp4"
    unrelated = media_dir / "trailer.mp4"
    large.write_bytes(b"x" * (2 * 1024 * 1024))
    small.write_bytes(b"x" * (512 * 1024))
    unrelated.write_bytes(b"x" * (3 * 1024 * 1024))

    job = JobStore(tmp_path / "jobs.sqlite3").create_job(
        str(media_dir), "/output", ["srt"], False, min_file_size_mb=1
    )

    assert job.input_size_bytes == large.stat().st_size


def test_download_job_output_returns_a_completed_subtitle_as_attachment(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from app import main

    subtitle = tmp_path / "FNS-192.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\ntext\n", encoding="utf-8")
    job = SimpleNamespace(id="done-job", status="done", output_files=[str(subtitle)])
    monkeypatch.setattr(main.job_store, "get_job", lambda job_id: job if job_id == job.id else None)

    response = main.download_job_output("done-job", 0)

    assert response.path == subtitle
    assert response.filename == subtitle.name


def test_delete_job_rejects_active_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from app import main

    active_job = SimpleNamespace(id="active-job", status="running")
    monkeypatch.setattr(main.job_store, "get_job", lambda job_id: active_job if job_id == active_job.id else None)
    monkeypatch.setattr(main.job_store, "delete_job", lambda job_id: True)

    with pytest.raises(HTTPException) as exc_info:
        main.delete_job(active_job.id)

    assert getattr(exc_info.value, "status_code", None) == 409


def test_public_version_endpoint_reports_v301(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    from app import main

    assert main.get_version() == {"version": "v3.01"}


def test_docker_compose_does_not_override_repo_branch():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "REPO_BRANCH:" not in compose


def test_dockerignore_excludes_local_runtime_and_verification_artifacts():
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

    for pattern in ("stitch-*", ".playwright-cli/", ".pytest_cache/", "output/", "cache/", "config/", "media/"):
        assert pattern in dockerignore


def test_config_store_persists_min_file_size_mb(tmp_path):
    store = ConfigStore(tmp_path / "config.json")

    saved = store.save({"min_file_size_mb": 0})
    loaded = store.load()

    assert saved.min_file_size_mb == 0
    assert loaded.min_file_size_mb == 0


def test_config_store_persists_smart_vad_flag(tmp_path):
    store = ConfigStore(tmp_path / "config.json")

    saved = store.save({"enable_smart_vad": True})
    loaded = store.load()

    assert saved.enable_smart_vad is True
    assert loaded.enable_smart_vad is True


def test_video_file_detection_is_case_insensitive():
    assert is_video_file(Path("/watch/Movie.MP4"))
    assert is_video_file(Path("/watch/clip.mkv"))
    assert not is_video_file(Path("/watch/subtitle.srt"))


def test_extract_av_code():
    assert extract_av_code(Path("/watch/hhd800.com@FNS-192.mp4")) == "FNS-192"
    assert extract_av_code(Path("/watch/EBWH-309.mp4")) == "EBWH-309"
    assert extract_av_code(Path("/watch/KYMI-054.mkv")) == "KYMI-054"
    assert extract_av_code(Path("/watch/NHDTB-963.mp4")) == "NHDTB-963"
    assert extract_av_code(Path("/watch/18+游戏大全-垃圾广告.mp4")) is None
    assert extract_av_code(Path("/watch/normal video.mp4")) is None


def test_extract_fc2_av_code_variants():
    assert extract_av_code(Path("/watch/FC2PPV-4907804.mp4")) == "FC2PPV-4907804"
    assert extract_av_code(Path("/watch/FC2-PPV-4907804.mp4")) == "FC2-PPV-4907804"
    assert extract_av_code(Path("/watch/FC2-4907804.mp4")) == "FC2-4907804"


def test_normalize_av_code_fc2_variants():
    assert normalize_av_code("FC2PPV-4907804") == "fc2-4907804"
    assert normalize_av_code("FC2-PPV-4907804") == "fc2-4907804"
    assert normalize_av_code("FC2-4907804") == "fc2-4907804"


def test_normalize_av_code_strips_numeric_prefix_for_non_fc2():
    assert normalize_av_code("300Mium-1336") == "mium-1336"
    assert normalize_av_code("250Idol-456") == "idol-456"
    assert normalize_av_code("FNS-192") == "fns-192"


def test_output_subtitle_path_uses_av_code():
    result = output_subtitle_path(Path("/watch/FNS-192/hhd800.com@FNS-192.mp4"), Path("/output"), "srt")
    assert result == Path("/output/FNS-192.srt")


def test_discover_media_filters_small_files_by_threshold(tmp_path):
    folder = tmp_path / "pred-877"
    folder.mkdir()
    keep = folder / "4k2.me@pred-877.mp4"
    skip = folder / "ad@pred-877.mp4"
    url_file = folder / "site.url"
    keep.write_bytes(b"a" * (101 * 1024 * 1024))
    skip.write_bytes(b"a" * (99 * 1024 * 1024))
    url_file.write_text("https://example.com", encoding="utf-8")

    result = discover_media(folder, min_file_size_mb=100)

    assert result == [keep]


def test_discover_media_single_file_below_threshold_returns_empty(tmp_path):
    media = tmp_path / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))

    assert discover_media(media, min_file_size_mb=100) == []


def test_discover_media_zero_threshold_disables_filter(tmp_path):
    media = tmp_path / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))

    assert discover_media(media, min_file_size_mb=0) == [media]


def test_list_small_av_files_returns_only_recognized_small_media(tmp_path):
    folder = tmp_path / "pred-877"
    folder.mkdir()
    small = folder / "PRED-877.mp4"
    large = folder / "SSIS-123.mp4"
    junk = folder / "note.txt"
    small.write_bytes(b"a" * (10 * 1024 * 1024))
    large.write_bytes(b"a" * (101 * 1024 * 1024))
    junk.write_text("skip", encoding="utf-8")

    result = list_small_av_files(folder, min_file_size_mb=100)

    assert result == [small]


def test_small_file_ignore_store_persists_and_matches_unchanged_snapshot(tmp_path):
    store = SmallFileIgnoreStore(tmp_path / "watchdog_ignored_small_files.json")
    entry = tmp_path / "PRED-877"
    entry.mkdir()
    media = entry / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))

    store.remember(entry, [media])

    reloaded = SmallFileIgnoreStore(tmp_path / "watchdog_ignored_small_files.json")
    assert reloaded.should_skip(entry) is True


def test_small_file_ignore_store_invalidates_when_size_changes(tmp_path):
    store = SmallFileIgnoreStore(tmp_path / "watchdog_ignored_small_files.json")
    entry = tmp_path / "PRED-877"
    entry.mkdir()
    media = entry / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))
    store.remember(entry, [media])

    media.write_bytes(b"a" * (11 * 1024 * 1024))

    assert store.should_skip(entry) is False


def test_small_file_ignore_store_invalidates_when_mtime_changes(tmp_path):
    import os
    import time

    store = SmallFileIgnoreStore(tmp_path / "watchdog_ignored_small_files.json")
    entry = tmp_path / "PRED-877"
    entry.mkdir()
    media = entry / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))
    store.remember(entry, [media])

    stat = media.stat()
    os.utime(media, (stat.st_atime, stat.st_mtime + 5))
    time.sleep(0.01)

    assert store.should_skip(entry) is False


def test_small_file_ignore_store_invalidates_when_new_av_file_appears(tmp_path):
    store = SmallFileIgnoreStore(tmp_path / "watchdog_ignored_small_files.json")
    entry = tmp_path / "PRED-877"
    entry.mkdir()
    media = entry / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))
    store.remember(entry, [media])

    another = entry / "SSIS-123.mp4"
    another.write_bytes(b"a" * (10 * 1024 * 1024))

    assert store.should_skip(entry) is False


def test_small_file_ignore_store_invalidates_when_file_disappears(tmp_path):
    store = SmallFileIgnoreStore(tmp_path / "watchdog_ignored_small_files.json")
    entry = tmp_path / "PRED-877"
    entry.mkdir()
    media = entry / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))
    store.remember(entry, [media])

    media.unlink()

    assert store.should_skip(entry) is False


def test_job_runner_marks_small_file_entry_as_skippable(tmp_path):
    watch_root = tmp_path / "watch"
    watch_root.mkdir()
    entry = watch_root / "PRED-877"
    entry.mkdir()
    media = entry / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))

    runner = JobRunner(JobStore(tmp_path / "jobs.sqlite3"), ConfigStore(tmp_path / "config.json"), watch_root, tmp_path / "cache")

    small_files = list_small_av_files(entry, min_file_size_mb=100)
    runner.small_file_ignore_store.remember(entry, small_files)

    assert runner.small_file_ignore_store.should_skip(entry) is True


def test_job_runner_small_file_entry_rechecks_after_growth(tmp_path):
    watch_root = tmp_path / "watch"
    watch_root.mkdir()
    entry = watch_root / "PRED-877"
    entry.mkdir()
    media = entry / "PRED-877.mp4"
    media.write_bytes(b"a" * (10 * 1024 * 1024))

    runner = JobRunner(JobStore(tmp_path / "jobs.sqlite3"), ConfigStore(tmp_path / "config.json"), watch_root, tmp_path / "cache")
    runner.small_file_ignore_store.remember(entry, list_small_av_files(entry, min_file_size_mb=100))

    media.write_bytes(b"a" * (101 * 1024 * 1024))

    assert runner.small_file_ignore_store.should_skip(entry) is False
    assert discover_media(entry, min_file_size_mb=100) == [media]


def test_watchdog_jobs_bind_the_active_modal_account(tmp_path, monkeypatch):
    watch_root = tmp_path / "watch"
    media_dir = watch_root / "HAWA-375"
    media_dir.mkdir(parents=True)
    (media_dir / "HAWA-375.mp4").write_bytes(b"media")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config_store = ConfigStore(tmp_path / "config.json")
    config_store.save({
        "enable_watchdog": True,
        "min_file_size_mb": 0,
        "default_output_dir": str(output_dir),
        "active_modal_account_id": "old-account",
        "modal_accounts": [{
            "id": "old-account",
            "name": "old",
            "token_id": "token-id",
            "token_secret": "token-secret",
            "hf_token": "",
        }],
    })
    store = JobStore(tmp_path / "jobs.sqlite3")
    runner = JobRunner(store, config_store, watch_root, tmp_path / "cache")
    runner._running = True

    async def stop_after_first_scan(_seconds):
        runner._running = False

    monkeypatch.setattr("app.worker.asyncio.sleep", stop_after_first_scan)
    asyncio.run(runner._watchdog_loop())

    jobs = store.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].modal_account_id == "old-account"


def test_build_ffmpeg_command_targets_cache_audio(tmp_path):
    command = build_ffmpeg_command(Path("/watch/movie.mp4"), tmp_path / "movie.m4a")

    assert command[:3] == ["ffmpeg", "-y", "-i"]
    assert str(tmp_path / "movie.m4a") == command[-1]
    assert "-vn" in command


def test_prepare_audio_reports_missing_input_path_before_running_ffmpeg(tmp_path):
    missing = tmp_path / "missing.mp4"

    with pytest.raises(RuntimeError, match="input path does not exist in container"):
        prepare_audio(missing, tmp_path)


def test_job_store_persists_and_updates_jobs(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    job = store.create_job(input_path="/watch/a.mp4", output_dir="/output", formats=["srt"], overwrite=False)
    store.update_job(job.id, status="running", message="started")
    loaded = store.get_job(job.id)

    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.message == "started"
    assert store.list_jobs()[0].id == job.id


def test_job_store_persists_live_phase_timings(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job("/watch/FNS-192.mp4", "/output", ["srt"], False)

    store.update_job(
        job.id,
        phase="cloud",
        phase_started_at=123.5,
        local_seconds=17.0,
        cloud_seconds=9.0,
    )
    loaded = store.get_job(job.id)

    assert loaded is not None
    assert loaded.phase == "cloud"
    assert loaded.phase_started_at == 123.5
    assert loaded.local_seconds == 17.0
    assert loaded.cloud_seconds == 9.0


def test_job_store_move_target_dir(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False, move_target_dir="/done")
    loaded = store.get_job(job.id)
    assert loaded.move_target_dir == "/done"


def test_cancel_queued_job(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False)
    assert store.cancel_job(job.id) is True
    loaded = store.get_job(job.id)
    assert loaded.status == "cancelled"


def test_cancel_running_job(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False)
    store.update_job(job.id, status="running")
    assert store.cancel_job(job.id) is True
    assert store.is_cancelling(job.id) is True


def test_cannot_cancel_done_job(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False)
    store.update_job(job.id, status="done")
    assert store.cancel_job(job.id) is False


def test_has_active_job_for_path(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    assert store.has_active_job_for_path("/watch/a.mp4") is False
    store.create_job("/watch/a.mp4", "/output", ["srt"], False)
    assert store.has_active_job_for_path("/watch/a.mp4") is True


def test_retry_failed_job(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False)
    store.update_job(job.id, status="failed", message="boom", started_at=123.0, completed_at=456.0, progress=99, output_files=["/output/a.srt"])

    assert store.retry_job(job.id) is True
    retried = store.get_job(job.id)
    assert retried is not None
    assert retried.status == "queued"
    assert retried.progress == 0
    assert retried.started_at == 0.0
    assert retried.completed_at == 0.0
    assert retried.output_files == []


def test_retry_all_failed_jobs(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    a = store.create_job("/watch/a.mp4", "/output", ["srt"], False)
    b = store.create_job("/watch/b.mp4", "/output", ["srt"], False)
    c = store.create_job("/watch/c.mp4", "/output", ["srt"], False)
    store.update_job(a.id, status="failed", progress=30)
    store.update_job(b.id, status="done")
    store.update_job(c.id, status="failed", progress=60)

    count = store.retry_all_failed_jobs()

    assert count == 2
    assert store.get_job(a.id).status == "queued"
    assert store.get_job(c.id).status == "queued"
    assert store.get_job(a.id).progress == 0
    assert store.get_job(c.id).progress == 0



def test_retry_cancelled_job(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False)
    store.update_job(job.id, status="cancelled", completed_at=123.0, progress=20)

    assert store.retry_job(job.id) is True
    retried = store.get_job(job.id)
    assert retried is not None
    assert retried.status == "queued"
    assert retried.progress == 0
    assert retried.completed_at == 0.0


def test_cannot_retry_non_failed_job(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)

    job = store.create_job("/watch/a.mp4", "/output", ["srt"], False)
    store.update_job(job.id, status="done")

    assert store.retry_job(job.id) is False


def test_modal_infer_patch_adds_include_source(tmp_path):
    repo_dir = tmp_path / "modal-repo"
    repo_dir.mkdir()
    modal_infer = repo_dir / "modal_infer.py"
    modal_infer.write_text(
        "import modal\napp = modal.App(\"subtitle-modal\")\n",
        encoding="utf-8",
    )
    runner = ModalRunner(AppConfig(), tmp_path)

    runner._patch_modal_infer(repo_dir)

    patched = modal_infer.read_text(encoding="utf-8")
    assert "include_source=True" in patched


def test_modal_infer_patch_makes_remote_repo_ref_configurable(tmp_path):
    repo_dir = tmp_path / "modal-repo"
    repo_dir.mkdir()
    modal_infer = repo_dir / "modal_infer.py"
    modal_infer.write_text(
        '''
import modal
app = modal.App("subtitle-modal")
def _remote_pipeline(job):
    if not (repo_dir / ".git").exists():
        log("开始克隆仓库...")
        run(["git", "clone", "--depth", "1", REPO_URL, str(repo_dir)])
    else:
        log("更新仓库...")
        run(["git", "-C", str(repo_dir), "fetch", "origin"])
        run(["git", "-C", str(repo_dir), "reset", "--hard", "origin/main"])
''',
        encoding="utf-8",
    )
    runner = ModalRunner(AppConfig(repo_branch="v1.10"), tmp_path)

    runner._patch_modal_infer(repo_dir)

    patched = modal_infer.read_text(encoding="utf-8")
    assert 'repo_ref = job.get("repo_ref") or "main"' in patched
    assert '"FETCH_HEAD"' in patched
    assert '"origin/main"' not in patched


def test_modal_infer_patch_passes_remote_smart_vad_arg(tmp_path):
    repo_dir = tmp_path / "modal-repo"
    repo_dir.mkdir()
    modal_infer = repo_dir / "modal_infer.py"
    modal_infer.write_text(
        '''
import modal
app = modal.App("subtitle-modal")
def _remote_pipeline(job):
    if job["enable_batching"]:
        cmd.append("--enable_batching")
        if job["batch_size"]:
            cmd.extend(["--batch_size", str(job["batch_size"])])
        cmd.extend(["--max_batch_size", str(job["max_batch_size"])])

    cmd.extend(job["remote_inputs"])
''',
        encoding="utf-8",
    )
    runner = ModalRunner(AppConfig(enable_smart_vad=False), tmp_path)

    runner._patch_modal_infer(repo_dir)

    patched = modal_infer.read_text(encoding="utf-8")
    assert 'job.get("supports_smart_vad")' in patched
    assert '"--smart_split_with_vad"' in patched
    assert 'smart_vad_value = "true" if job.get("smart_split_with_vad") else "false"' in patched


@pytest.mark.parametrize(
    ("disconnect_type", "failed_gets", "expect_success"),
    [("modal", 1, True), ("grpclib", 1, True), ("modal", 2, False)],
)
def test_modal_infer_patch_retries_the_same_function_call_after_disconnect(
    tmp_path, monkeypatch, disconnect_type, failed_gets, expect_success
):
    repo_dir = tmp_path / "modal-repo"
    repo_dir.mkdir()
    modal_infer = repo_dir / "modal_infer.py"
    modal_infer.write_text(
        '''
def run_remote_pipeline(payload, selection):
    with app.run():
        result = modal_pipeline.remote(payload)
    return result
''',
        encoding="utf-8",
    )
    runner = ModalRunner(AppConfig(), tmp_path)

    runner._patch_modal_infer(repo_dir)

    patched = modal_infer.read_text(encoding="utf-8")
    assert "function_call = modal_pipeline.spawn(payload)" in patched
    assert "function_call.get(timeout=selection.timeout_minutes * 60)" in patched
    assert "modal.exception.ConnectionError" in patched
    assert "grpclib.exceptions" in patched
    assert patched.count("modal_pipeline.spawn(payload)") == 1
    assert "modal_pipeline.remote(payload)" not in patched

    class ModalConnectionError(Exception):
        pass

    class StreamTerminatedError(Exception):
        pass

    grpclib_package = ModuleType("grpclib")
    grpclib_exceptions = ModuleType("grpclib.exceptions")
    grpclib_exceptions.StreamTerminatedError = StreamTerminatedError
    grpclib_package.exceptions = grpclib_exceptions
    monkeypatch.setitem(sys.modules, "grpclib", grpclib_package)
    monkeypatch.setitem(sys.modules, "grpclib.exceptions", grpclib_exceptions)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    disconnect_error = ModalConnectionError if disconnect_type == "modal" else StreamTerminatedError
    calls = {"spawn": 0, "get": 0}

    class FunctionCall:
        def get(self, timeout):
            calls["get"] += 1
            assert timeout == 60
            if calls["get"] <= failed_gets:
                raise disconnect_error("connection dropped")
            return "finished"

    class Pipeline:
        def spawn(self, payload):
            calls["spawn"] += 1
            assert payload == {"job": "same-invocation"}
            return FunctionCall()

    class App:
        def run(self):
            class Context:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return Context()

    namespace = {
        "app": App(),
        "logging": SimpleNamespace(warning=lambda *_args: None),
        "modal": SimpleNamespace(exception=SimpleNamespace(ConnectionError=ModalConnectionError)),
        "modal_pipeline": Pipeline(),
    }
    exec(compile(patched, str(modal_infer), "exec"), namespace)

    run_remote_pipeline = namespace["run_remote_pipeline"]
    args = ({"job": "same-invocation"}, SimpleNamespace(timeout_minutes=1))
    if expect_success:
        assert run_remote_pipeline(*args) == "finished"
    else:
        with pytest.raises(disconnect_error, match="connection dropped"):
            run_remote_pipeline(*args)

    assert calls == {"spawn": 1, "get": 2}


def test_modal_runner_skips_recent_fetch_only_for_same_repo_ref(tmp_path, monkeypatch):
    repo_dir = tmp_path / "modal-repo"
    git_dir = repo_dir / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "last_fetch").write_text("v1.10", encoding="utf-8")
    calls = []
    monkeypatch.setattr("app.modal_runner.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    ModalRunner(AppConfig(repo_branch="v1.10"), tmp_path)._ensure_repo(repo_dir)

    assert calls == []


def test_modal_bridge_submit_failure_includes_stderr(tmp_path):
    class FakeStream:
        def __init__(self, lines):
            self._lines = iter(lines)

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._lines)

        def read(self):
            return ""

    class FakeProc:
        def __init__(self):
            self.stdout = FakeStream(["[modal_stage] import_modal\n"])
            self.stderr = FakeStream(["actual modal auth failure\n"])
            self._polled = True

        def poll(self):
            return 1

        def kill(self):
            pass

        def wait(self):
            pass

    proc = FakeProc()
    handle = ModalRunHandle(proc, tmp_path, ["srt"], {})

    with pytest.raises(RuntimeError) as exc:
        handle.wait_for_submit(timeout_seconds=5)

    assert "Modal bridge failed before cloud submission" in str(exc.value)
    assert "actual modal auth failure" in str(exc.value)


def test_modal_connection_error_detection_only_matches_transient_disconnects():
    assert is_transient_modal_connection_error(
        RuntimeError("modal.exception.ConnectionError: Connection lost")
    ) is True
    assert is_transient_modal_connection_error(
        RuntimeError("grpclib.exceptions.StreamTerminatedError: connection closed")
    ) is True
    assert is_transient_modal_connection_error(
        RuntimeError("Modal Token validation failed")
    ) is False
    assert is_transient_modal_connection_error(
        RuntimeError("database connection closed")
    ) is False


def test_modal_client_wait_timeout_includes_reconnect_margin():
    assert modal_client_wait_timeout(7200) == 7500


def test_modal_runner_fetches_when_repo_ref_changes(tmp_path, monkeypatch):
    repo_dir = tmp_path / "modal-repo"
    git_dir = repo_dir / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "last_fetch").write_text("v1.10", encoding="utf-8")
    calls = []
    monkeypatch.setattr("app.modal_runner.subprocess.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    ModalRunner(AppConfig(repo_branch="v1.7"), tmp_path)._ensure_repo(repo_dir)

    assert calls[0][0][0] == ["git", "fetch", "--depth", "1", "origin", "v1.7"]
    assert calls[1][0][0] == ["git", "reset", "--hard", "FETCH_HEAD"]
    assert (git_dir / "last_fetch").read_text(encoding="utf-8") == "v1.7"


def test_modal_runner_disables_supported_smart_vad_config(tmp_path):
    repo_dir = tmp_path / "modal-repo"
    repo_dir.mkdir()
    infer_dir = repo_dir / "src" / "faster_whisper_transwithai_chickenrice"
    infer_dir.mkdir(parents=True)
    (infer_dir / "infer.py").write_text("smart_split_with_vad", encoding="utf-8")
    config_file = repo_dir / "generation_config.json5"
    config_file.write_text('{"smart_split_with_vad": true, "target_chunk_duration_s": 30}', encoding="utf-8")
    runner = ModalRunner(AppConfig(enable_smart_vad=False), tmp_path)

    runner._configure_smart_vad(repo_dir)

    assert '"smart_split_with_vad": false' in config_file.read_text(encoding="utf-8")


def test_modal_runner_enables_supported_smart_vad_config(tmp_path):
    repo_dir = tmp_path / "modal-repo"
    repo_dir.mkdir()
    infer_dir = repo_dir / "src" / "faster_whisper_transwithai_chickenrice"
    infer_dir.mkdir(parents=True)
    (infer_dir / "infer.py").write_text("smart_split_with_vad", encoding="utf-8")
    config_file = repo_dir / "generation_config.json5"
    config_file.write_text('{"smart_split_with_vad": false, "target_chunk_duration_s": 30}', encoding="utf-8")
    runner = ModalRunner(AppConfig(enable_smart_vad=True), tmp_path)

    runner._configure_smart_vad(repo_dir)

    assert '"smart_split_with_vad": true' in config_file.read_text(encoding="utf-8")


def test_modal_runner_leaves_unsupported_smart_vad_repo_unchanged(tmp_path):
    repo_dir = tmp_path / "modal-repo"
    repo_dir.mkdir()
    infer_dir = repo_dir / "src" / "faster_whisper_transwithai_chickenrice"
    infer_dir.mkdir(parents=True)
    (infer_dir / "infer.py").write_text("older infer", encoding="utf-8")
    config_file = repo_dir / "generation_config.json5"
    original = '{"task": "translate"}'
    config_file.write_text(original, encoding="utf-8")
    runner = ModalRunner(AppConfig(enable_smart_vad=True), tmp_path)

    runner._configure_smart_vad(repo_dir)

    assert config_file.read_text(encoding="utf-8") == original


def test_job_runner_formats_modal_token_validation_errors():
    raw = (
        "Modal bridge failed before cloud submission:\n"
        "[modal_stage] import_modal\n"
        "Traceback (most recent call last):\n"
        "modal.exception.AuthError: Token validation failed"
    )

    assert JobRunner._format_error_message(RuntimeError(raw)) == (
        "Modal Token 验证失败：请在配置页检查当前 Modal 账户的 Token ID / Token Secret，保存后重试。"
    )


def test_job_runner_formats_retried_modal_connection_errors():
    raw = "Modal run failed: modal.exception.ConnectionError: Connection lost"

    message = JobRunner._format_error_message(RuntimeError(raw))

    assert "已自动重试 1 次" in message
    assert "重新生成旧账号 Token" in message
    assert "Traceback" not in message


def test_job_runner_persists_formatted_modal_connection_failure(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job("/watch/HAWA-375.mp4", "/output", ["srt"], False)
    runner = JobRunner(store, ConfigStore(tmp_path / "config.json"), tmp_path, tmp_path / "cache")

    runner._record_job_failure(
        job.id,
        "云端推理中 1/1",
        RuntimeError("modal.exception.ConnectionError: Connection lost\nTraceback: noisy"),
    )

    failed = store.get_job(job.id)
    assert failed.status == "failed"
    assert "已自动重试 1 次" in failed.message
    assert "Traceback" not in failed.message


def test_normalize_outputs_returns_only_existing_files(tmp_path):
    """验证 _normalize_outputs 不返回已删除的路径"""
    from app.worker import JobRunner

    # 场景：produced 有 .vtt 文件，但 expected 只要 .srt
    # cleanup 循环会删除 .vtt 文件，此时不应返回已删除的路径
    vtt_file = tmp_path / "orphan.vtt"
    vtt_file.write_text("vtt content", encoding="utf-8")

    result = JobRunner._normalize_outputs(
        produced=[vtt_file],
        expected=[tmp_path / "expected.srt"]
    )
    # vtt 文件被 cleanup 删除，应返回空列表（不是 [vtt_file]）
    assert result == []
    assert not vtt_file.exists()


def test_normalize_outputs_moves_and_returns_existing(tmp_path):
    """验证 _normalize_outputs 正确移动文件并返回存在的路径"""
    from app.worker import JobRunner

    source = tmp_path / "source.srt"
    source.write_text("subtitle content", encoding="utf-8")
    target = tmp_path / "target.srt"

    result = JobRunner._normalize_outputs(
        produced=[source],
        expected=[target]
    )

    assert len(result) == 1
    assert result[0] == target
    assert target.exists()
    assert not source.exists()


def test_normalize_outputs_cleans_leftovers(tmp_path):
    """验证 _normalize_outputs 清理未匹配的脏文件"""
    from app.worker import JobRunner

    good = tmp_path / "good.srt"
    good.write_text("good", encoding="utf-8")
    dirty = tmp_path / "dirty.com@START-554.srt"
    dirty.write_text("dirty", encoding="utf-8")
    target = tmp_path / "good.srt"

    result = JobRunner._normalize_outputs(
        produced=[good, dirty],
        expected=[target]
    )

    assert len(result) == 1
    assert result[0] == target
    assert not dirty.exists()  # 脏文件应被清理
