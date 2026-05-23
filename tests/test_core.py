import os
from pathlib import Path

from app.config import AppConfig, ConfigStore
from app.media import build_ffmpeg_command, extract_av_code, is_video_file, output_subtitle_path
from app.modal_runner import ModalRunner
from app.storage import JobStore


def test_config_env_overrides_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"modal_token_id":"file-id","default_gpu":"A10G"}', encoding="utf-8")
    monkeypatch.setenv("MODAL_TOKEN_ID", "env-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "env-secret")

    config = ConfigStore(config_path).load()

    assert config.modal_token_id == "env-id"
    assert config.modal_token_secret == "env-secret"
    assert config.default_gpu == "A10G"
    assert config.redacted()["modal_token_id"] == "env-***"
    assert config.redacted()["modal_token_secret"] == "env-***"


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


def test_output_subtitle_path_uses_av_code():
    result = output_subtitle_path(Path("/watch/FNS-192/hhd800.com@FNS-192.mp4"), Path("/output"), "srt")
    assert result == Path("/output/FNS-192.srt")


def test_build_ffmpeg_command_targets_cache_audio(tmp_path):
    command = build_ffmpeg_command(Path("/watch/movie.mp4"), tmp_path / "movie.m4a")

    assert command[:3] == ["ffmpeg", "-y", "-i"]
    assert str(tmp_path / "movie.m4a") == command[-1]
    assert "-vn" in command


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

