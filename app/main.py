from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
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
    min_file_size_mb: int | None = Field(default=None, ge=0)
    default_timeout_seconds: int | None = Field(default=None, ge=60, le=86400)
    default_move_target_dir: str | None = None
    enable_watchdog: bool | None = None
    watchdog_interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    max_workers: int | None = Field(default=None, ge=1, le=10)
    dbo_api_url: str | None = None
    dbo_api_key: str | None = None


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


@app.get("/api/dbo-search")
def dbo_search(q: str, limit: int = 1) -> dict:
    """DBO 搜索代理 — 浏览器不直连内网，走后端转发"""
    cfg = config_store.load()
    if not cfg.dbo_api_url or not cfg.dbo_api_key:
        raise HTTPException(status_code=503, detail="DBO 未配置")
    try:
        req = urllib.request.Request(
            f"{cfg.dbo_api_url}/api/search?q={urllib.parse.quote(q)}&limit={limit}",
            headers={"X-API-Key": cfg.dbo_api_key},
        )
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DBO search failed: {e}")


@app.post("/api/test-dbo")
def test_dbo() -> dict:
    """测试 DBO API 连通性"""
    cfg = config_store.load()
    if not cfg.dbo_api_url or not cfg.dbo_api_key:
        return {"ok": False, "error": "DBO 未配置"}
    import time as _time
    t0 = _time.time()
    try:
        req = urllib.request.Request(
            f"{cfg.dbo_api_url}/api/search?q=test&limit=1",
            headers={"X-API-Key": cfg.dbo_api_key},
        )
        urllib.request.urlopen(req, timeout=10)
        return {"ok": True, "latency_ms": round((_time.time() - t0) * 1000), "url": cfg.dbo_api_url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "url": cfg.dbo_api_url}


@app.get("/api/version")
def get_version() -> dict:
    return {"version": "v2.10"}


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
    if job_store.has_active_job_for_path(payload.input_path):
        raise HTTPException(status_code=409, detail="该路径已有运行中或排队的任务")

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


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    ok = job_store.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    ok = job_store.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="job cannot be cancelled (not queued/running, or already done)")
    job = job_store.get_job(job_id)
    return asdict(job) if job else {}



# ═══ POSTER PROXY (dbo -> frontend) ═══
import urllib.request
import urllib.parse

@app.post("/api/clear-audio-cache")
def clear_audio_cache() -> dict:
    """清空音频缓存目录"""
    audio_dir = Path(CACHE_DIR) / "audio"
    removed = 0
    if audio_dir.exists():
        for f in audio_dir.iterdir():
            if f.is_file():
                f.unlink()
                removed += 1
    return {"removed": removed}


@app.get("/api/pack")
def pack_jobs(date: str):
    """打包某一天所有已完成任务的字幕文件"""
    try:
        date_start = float(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")
    jobs = job_store.get_by_completion_date(date_start)
    if not jobs:
        raise HTTPException(status_code=404, detail="no jobs found for this date")

    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for job in jobs:
            for filepath in job.output_files:
                p = Path(filepath)
                if p.exists():
                    zf.write(p, p.name)
                else:
                    zf.writestr(f"(missing)_{p.name}", f"file not found: {filepath}")
    buf.seek(0)

    d = date_start
    from datetime import datetime, timezone, timedelta
    from urllib.parse import quote
    tz = timezone(timedelta(hours=8))
    label = datetime.fromtimestamp(d, tz=tz).strftime("%Y%m%d")
    filename_en = f"{label}-{len(jobs)}.zip"
    filename_cn = f"{label}-{len(jobs)}部.zip"

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename_en}\"; filename*=UTF-8''{quote(filename_cn)}"
        }
    )

# 允许代理的图片 CDN 域名白名单
_ALLOWED_IMAGE_DOMAINS = {
    "tp.cmastd.com", "tp.spfcas.com",
    "pics.dmm.co.jp", "image.mgstage.com",
    "pics.r18.com", "imgr18.shemalejapanhardcore.com",
}

@app.get("/api/poster-proxy")
def poster_proxy(url: str):
    cfg = config_store.load()
    if not cfg.dbo_api_url or not cfg.dbo_api_key:
        raise HTTPException(status_code=503, detail="DBO 未配置")
    if not url or not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="invalid url")
    # SSRF 防护：只允许白名单域名
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        raise HTTPException(status_code=400, detail="invalid url")
    if not any(host == d or host.endswith("." + d) for d in _ALLOWED_IMAGE_DOMAINS):
        raise HTTPException(status_code=400, detail="domain not allowed")
    dbo_url = f"{cfg.dbo_api_url}/api/image?url={urllib.parse.quote(url)}"
    req = urllib.request.Request(dbo_url, headers={"X-API-Key": cfg.dbo_api_key})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return Response(content=r.read(), media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"dbo image fetch failed: {e}")
