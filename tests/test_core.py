import os
from pathlib import Path

import pytest

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
from app.modal_runner import ModalRunner
from app.storage import JobStore
from app.worker import JobRunner, SmallFileIgnoreStore


def test_config_env_overrides_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"modal_token_id":"file-id","default_gpu":"A10G"}', encoding="utf-8")
    monkeypatch.setenv("MODAL_TOKEN_ID", "env-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "env-secret")

    config = ConfigStore(config_path).load()

    assert config.modal_token_id == "env-id"
    assert config.modal_token_secret == "env-secret"
    assert config.default_gpu == "A10G"
    assert config.redacted()["modal_token_id"] == "***"
    assert config.redacted()["modal_token_secret"] == "env***ret"


def test_config_defaults_include_min_file_size_mb():
    config = AppConfig()

    assert config.min_file_size_mb == 100


def test_config_store_persists_min_file_size_mb(tmp_path):
    store = ConfigStore(tmp_path / "config.json")

    saved = store.save({"min_file_size_mb": 0})
    loaded = store.load()

    assert saved.min_file_size_mb == 0
    assert loaded.min_file_size_mb == 0


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
