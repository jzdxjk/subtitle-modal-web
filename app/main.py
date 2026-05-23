from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from pathlib import Path

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ConfigStore
from app.storage import JobStore
from app.worker import JobRunner

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "/cache"))
WATCH_DIR = Path(os.getenv("WATCH_DIR", "/watch"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/output"))

config_store = ConfigStore(CONFIG_DIR / "config.json")
job_store = JobStore(CONFIG_DIR / "jobs.sqlite3")
runner = JobRunner(job_store, config_store, WATCH_DIR, CACHE_DIR)

app = FastAPI(title="Subtitle Modal Web")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class ConfigPayload(BaseModel):
    modal_token_id: str | None = None
    modal_token_secret: str | None = None
    hf_token: str | None = None
    default_gpu: str | None = None
    default_model: str | None = None
    default_output_dir: str | None = None
    default_cache_dir: str | None = None
    default_formats: str | None = None
    default_timeout_seconds: int | None = Field(default=None, ge=60, le=86400)
    default_move_target_dir: str | None = None
    enable_watchdog: bool | None = None
    watchdog_interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    max_workers: int | None = Field(default=None, ge=1, le=10)


class JobPayload(BaseModel):
    input_path: str
    output_dir: str = str(OUTPUT_DIR)
    formats: list[str] = Field(default_factory=lambda: ["srt"])
    overwrite: bool = False
    move_target_dir: str = ""


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(runner.start())


@app.on_event("shutdown")
async def shutdown() -> None:
    runner.stop()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/config")
def get_config() -> dict:
    return config_store.load().redacted()


@app.post("/api/config")
def save_config(payload: ConfigPayload) -> dict:
    data = payload.dict(exclude_none=True)
    return config_store.save(data).redacted()


@app.post("/api/jobs")
def create_job(payload: JobPayload) -> dict:
    path = Path(payload.input_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"input path does not exist: {payload.input_path}")
    formats = [fmt.strip().lstrip(".").lower() for fmt in payload.formats if fmt.strip()]
    if not formats:
        raise HTTPException(status_code=400, detail="at least one subtitle format is required")
    job = job_store.create_job(payload.input_path, payload.output_dir, formats, payload.overwrite, payload.move_target_dir)
    return asdict(job)


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [asdict(job) for job in job_store.list_jobs()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return asdict(job)


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    ok = job_store.retry_job(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="job cannot be retried (not failed/cancelled, or not found)")
    job = job_store.get_job(job_id)
    return asdict(job) if job else {}


@app.post("/api/jobs/retry-failed")
def retry_failed_jobs() -> dict:
    retried = job_store.retry_all_failed_jobs()
    return {"retried": retried}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    ok = job_store.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="job cannot be cancelled (not queued/running, or already done)")
    job = job_store.get_job(job_id)
    return asdict(job) if job else {}

