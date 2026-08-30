from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from fastapi import FastAPI, HTTPException
from fastapi import Header
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ConfigStore
from app.media import resolve_emby_media_path
from app.metadata_api import JAVDB_NODES, MetadataClient
from app.storage import JobStore
from app.worker import JobRunner

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "/cache"))
WATCH_DIR = Path(os.getenv("WATCH_DIR", "/watch"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/output"))
PLUGIN_MEDIA_ROOT = Path(os.getenv("PLUGIN_MEDIA_ROOT", str(WATCH_DIR.parent)))
JA_SUBS_DIR = Path("/ja_subs")

# 启动前验证关键目录，避免挂载遗漏导致静默失败
for _dir, _name in [(WATCH_DIR, "WATCH_DIR"), (OUTPUT_DIR, "OUTPUT_DIR"), (CACHE_DIR, "CACHE_DIR")]:
    if not _dir.exists():
        raise RuntimeError(
            f"{_name} 目录不存在: {_dir}。请检查 docker-compose.yml 的 volumes 挂载配置。"
        )

config_store = ConfigStore(CONFIG_DIR / "config.json")
initial_config = config_store.load()
job_store = JobStore(
    CONFIG_DIR / "jobs.sqlite3",
    min_file_size_mb=initial_config.min_file_size_mb,
    default_move_target_dir=initial_config.default_move_target_dir,
)
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
    enable_smart_vad: bool | None = None
    metadata_provider: str | None = None
    javdb_api_url: str | None = None
    poster_decrypt: bool | None = None
    dbo_api_url: str | None = None
    dbo_api_key: str | None = None
    enable_transcribe: bool | None = None
    openai_api_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    transcribe_prompt: str | None = None
    transcribe_model: str | None = None
    repo_branch: str | None = None
    plugin_api_token: str | None = None


class JobPayload(BaseModel):
    input_path: str
    output_dir: str = str(OUTPUT_DIR)
    formats: list[str] = Field(default_factory=lambda: ["srt"])
    overwrite: bool = False
    move_target_dir: str = ""


class PluginJobPayload(BaseModel):
    input_path: str
    emby_item_id: str = ""
    display_title: str = ""
    av_code: str = ""
    poster_url: str = ""
    task_type: str = "native"
    formats: list[str] = Field(default_factory=lambda: ["srt"])
    overwrite: bool = False


class ModalAccountPayload(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=64)
    token_id: str = ""
    token_secret: str = ""
    hf_token: str = ""


class MetadataNodeSelection(BaseModel):
    node_id: str


class PluginRefreshPayload(BaseModel):
    state: str
    message: str = ""


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
    """Provider-neutral metadata search kept under the legacy browser route."""
    cfg = config_store.load()
    try:
        return MetadataClient(cfg).search(q, limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Metadata search failed: {e}")


@app.get("/api/metadata-nodes")
def list_metadata_nodes() -> dict:
    return {"nodes": MetadataClient(config_store.load()).nodes()}


@app.post("/api/metadata-nodes/probe")
def probe_metadata_nodes() -> dict:
    return {"nodes": MetadataClient(config_store.load()).probe_nodes()}


@app.post("/api/metadata-nodes/{node_id}/probe")
def probe_metadata_node(node_id: str) -> dict:
    try:
        return MetadataClient(config_store.load()).probe_node(node_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="API 节点不存在")


@app.post("/api/metadata-nodes/select")
def select_metadata_node(payload: MetadataNodeSelection) -> dict:
    config = config_store.load()
    if payload.node_id == "dbo":
        if not config.dbo_api_url or not config.dbo_api_key:
            raise HTTPException(status_code=400, detail="请先保存 DBO API 地址和密钥")
        return config_store.save({"metadata_provider": "dbo"}).redacted()
    node = next((item for item in JAVDB_NODES if item["id"] == payload.node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="API 节点不存在")
    return config_store.save({
        "metadata_provider": "javdb",
        "javdb_api_url": node["url"],
    }).redacted()


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
    return {"version": "v3.06"}


@app.get("/api/config")
def get_config() -> dict:
    return config_store.load().redacted()


@app.post("/api/config")
def save_config(payload: ConfigPayload) -> dict:
    data = payload.dict(exclude_none=True)
    return config_store.save(data).redacted()


@app.get("/api/modal-accounts")
def list_modal_accounts() -> dict:
    config = config_store.load().redacted()
    return {"accounts": config["modal_accounts"], "active_account_id": config["active_modal_account_id"]}


@app.post("/api/modal-accounts")
def save_modal_account(payload: ModalAccountPayload) -> dict:
    if not payload.token_id or not payload.token_secret:
        existing = config_store.get_modal_account(payload.id or "")
        if existing is None:
            raise HTTPException(status_code=400, detail="Modal Token ID 和 Token Secret 不能为空")
    config = config_store.save_modal_account(payload.dict())
    return config.redacted()


@app.post("/api/modal-accounts/{account_id}/activate")
def activate_modal_account(account_id: str) -> dict:
    try:
        return config_store.set_active_modal_account(account_id).redacted()
    except KeyError:
        raise HTTPException(status_code=404, detail="账户不存在")


@app.delete("/api/modal-accounts/{account_id}")
def delete_modal_account(account_id: str) -> dict:
    if job_store.has_active_jobs_for_modal_account(account_id):
        raise HTTPException(status_code=409, detail="该账户仍有排队或运行中的任务，暂不能删除")
    if config_store.get_modal_account(account_id) is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    return config_store.delete_modal_account(account_id).redacted()


@app.get("/api/modal-cost/month")
def modal_monthly_cost() -> dict:
    config = config_store.load()
    account = config_store.get_modal_account(config.active_modal_account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="请先配置并选择 Modal 账户")
    env = os.environ.copy()
    env["MODAL_TOKEN_ID"] = account["token_id"]
    env["MODAL_TOKEN_SECRET"] = account["token_secret"]
    try:
        result = subprocess.run(["modal", "billing", "report", "--for", "this month", "--json"], env=env, capture_output=True, text=True, timeout=30, check=True)
        report = json.loads(result.stdout)
        total = sum(float(item.get("cost", 0) or 0) for item in report if isinstance(item, dict))
        return {"account_name": account["name"], "cost": total}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"无法查询 Modal 本月费用: {exc}")


# ═══ TRANSCRIBE API ═══

class TranscribeConfigPayload(BaseModel):
    enable_transcribe: bool | None = None
    openai_api_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    transcribe_prompt: str | None = None
    transcribe_model: str | None = None


@app.post("/api/transcribe-config")
def save_transcribe_config(payload: TranscribeConfigPayload) -> dict:
    """仅保存转录相关配置"""
    data = payload.dict(exclude_none=True)
    return config_store.save(data).redacted()


@app.post("/api/transcribe/models")
def fetch_openai_models() -> dict:
    """代理获取 OpenAI 兼容 API 的模型列表"""
    cfg = config_store.load()
    if not cfg.openai_api_url or not cfg.openai_api_key:
        raise HTTPException(status_code=400, detail="OpenAI API URL 或 Key 未配置")
    url = cfg.openai_api_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {cfg.openai_api_key}"})
    try:
        r = urllib.request.urlopen(req, timeout=15)
        data = json.loads(r.read())
        models = sorted([m["id"] for m in data.get("data", []) if m.get("id")])
        return {"ok": True, "models": models}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取模型列表失败: {e}")


@app.post("/api/transcribe/test")
def test_openai_connection() -> dict:
    """测试 OpenAI 兼容 API 连通性"""
    cfg = config_store.load()
    if not cfg.openai_api_url or not cfg.openai_api_key:
        return {"ok": False, "error": "OpenAI API URL 或 Key 未配置"}
    import time as _time
    t0 = _time.time()
    url = cfg.openai_api_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": cfg.openai_model or "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {cfg.openai_api_key}",
        "Content-Type": "application/json",
    })
    try:
        r = urllib.request.urlopen(req, timeout=15)
        resp = json.loads(r.read())
        model_used = resp.get("model", "unknown")
        return {"ok": True, "latency_ms": round((_time.time() - t0) * 1000), "model": model_used}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


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
    config = config_store.load()
    account = config_store.get_modal_account(config.active_modal_account_id)
    if account is None or not account.get("token_id") or not account.get("token_secret"):
        raise HTTPException(status_code=400, detail="请先在配置页选择并保存有效的 Modal 账户")
    job = job_store.create_job(
        payload.input_path,
        payload.output_dir,
        formats,
        payload.overwrite,
        payload.move_target_dir,
        config.active_modal_account_id,
        min_file_size_mb=config.min_file_size_mb,
    )
    return asdict(job)


def _plugin_auth(token: str | None) -> None:
    expected = config_store.load().plugin_api_token
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid plugin token")


@app.get("/api/plugin/health")
def plugin_health(x_api_token: str | None = Header(default=None)) -> dict:
    _plugin_auth(x_api_token)
    return {"ok": True, "plugin_api_enabled": bool(config_store.load().plugin_api_token)}


@app.post("/api/plugin/jobs")
def create_plugin_job(payload: PluginJobPayload, x_api_token: str | None = Header(default=None)) -> dict:
    _plugin_auth(x_api_token)
    path = resolve_emby_media_path(payload.input_path, PLUGIN_MEDIA_ROOT)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"input path does not exist: {payload.input_path}")
    resolved_path = str(path)
    if job_store.has_active_job_for_path(resolved_path):
        existing = next((j for j in job_store.list_jobs() if j.input_path == resolved_path and j.status in {"queued", "running", "cancelling"}), None)
        return asdict(existing) if existing else {"deduplicated": True}
    task_type = payload.task_type
    if path.suffix.lower() == ".strm" and task_type == "native":
        from app.media import classify_strm_source
        try:
            task_type, _ = classify_strm_source(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    config = config_store.load()
    account = config_store.get_modal_account(config.active_modal_account_id)
    if account is None or not account.get("token_id") or not account.get("token_secret"):
        raise HTTPException(status_code=400, detail="请先配置有效的 Modal 账户")
    formats = [fmt.strip().lstrip(".").lower() for fmt in payload.formats if fmt.strip()]
    if not formats:
        raise HTTPException(status_code=400, detail="at least one subtitle format is required")
    if payload.task_type not in {"native", "strm-http", "strm-local"}:
        raise HTTPException(status_code=400, detail="invalid plugin task type")
    job = job_store.create_job(
        resolved_path, str(path.parent), formats, payload.overwrite, "", config.active_modal_account_id,
        source="emby", task_type=task_type, emby_item_id=payload.emby_item_id,
        display_title=payload.display_title, av_code=payload.av_code, poster_url=payload.poster_url,
    )
    return asdict(job)


@app.get("/api/plugin/jobs")
def list_plugin_jobs(x_api_token: str | None = Header(default=None)) -> list[dict]:
    _plugin_auth(x_api_token)
    return [asdict(job) for job in job_store.list_jobs() if job.source == "emby"]


@app.get("/api/plugin/jobs/{job_id}")
def get_plugin_job(job_id: str, x_api_token: str | None = Header(default=None)) -> dict:
    _plugin_auth(x_api_token)
    job = job_store.get_job(job_id)
    if job is None or job.source != "emby":
        raise HTTPException(status_code=404, detail="plugin job not found")
    return asdict(job)


@app.post("/api/plugin/jobs/{job_id}/refresh-result")
def plugin_refresh_result(job_id: str, payload: PluginRefreshPayload | None = None, refresh_state: str | None = None, x_api_token: str | None = Header(default=None)) -> dict:
    _plugin_auth(x_api_token)
    job = job_store.get_job(job_id)
    if job is None or job.source != "emby":
        raise HTTPException(status_code=404, detail="plugin job not found")
    state = payload.state if payload else (refresh_state or "pending")
    message = payload.message if payload else ""
    if state not in {"pending", "refreshing", "success", "failed"}:
        raise HTTPException(status_code=422, detail="invalid refresh state")
    job_store.update_job(job_id, refresh_state=state, message=message or job.message)
    return {"ok": True, "refresh_state": state, "message": message}


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [asdict(job) for job in job_store.list_jobs()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return asdict(job)


@app.get("/api/jobs/{job_id}/download")
def download_job_output(job_id: str, file_index: int = 0) -> FileResponse:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job output is not ready")
    if file_index < 0 or file_index >= len(job.output_files):
        raise HTTPException(status_code=404, detail="output file not found")

    output_file = Path(job.output_files[file_index])
    if not output_file.is_file():
        raise HTTPException(status_code=404, detail="output file is missing")
    return FileResponse(output_file, filename=output_file.name)


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
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in ("queued", "running"):
        raise HTTPException(status_code=409, detail="active job must be cancelled before deletion")
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
def pack_jobs(date: str, av: str | None = None):
    """打包某一天字幕，传 av 时只打包该作品。"""
    try:
        date_start = float(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")
    jobs = job_store.get_by_completion_date(date_start)
    if av:
        wanted = av.casefold()
        jobs = [j for j in jobs if (j.av_code or "").casefold() == wanted or any(wanted in Path(f).stem.casefold() for f in j.output_files)]
    if not jobs:
        raise HTTPException(status_code=404, detail="no jobs found for this date")

    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_names: set[str] = set()
        for job in jobs:
            for filepath in job.output_files:
                p = Path(filepath)
                if p.exists():
                    arcname = p.name
                    if av:
                        stem = p.stem
                        if "-CD" not in stem:
                            match = re.search(r"(?:part|cd)[_ -]?(\d+)", Path(job.input_path).stem, re.I)
                            if match:
                                arcname = f"{av}-CD{match.group(1)}{p.suffix}"
                        arcname = arcname.upper() if arcname.lower().endswith(".srt") else arcname
                    if arcname in seen_names:
                        continue
                    seen_names.add(arcname)
                    zf.write(p, arcname)
    buf.seek(0)

    d = date_start
    from datetime import datetime, timezone, timedelta
    from urllib.parse import quote
    tz = timezone(timedelta(hours=8))
    label = datetime.fromtimestamp(d, tz=tz).strftime("%Y%m%d")
    filename_en = f"{av}.zip" if av else f"{label}-{len(jobs)}.zip"
    filename_cn = f"{av}.zip" if av else f"{label}-{len(jobs)}部.zip"

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename_en}\"; filename*=UTF-8''{quote(filename_cn)}"
        }
    )

# 允许代理的图片 CDN 域名白名单
_ALLOWED_IMAGE_DOMAINS = {
    "jdbstatic.com", "c0.jdbstatic.com",
    "tp.cmastd.com", "tp.spfcas.com",
    "pics.dmm.co.jp", "image.mgstage.com",
    "pics.r18.com", "imgr18.shemalejapanhardcore.com",
}
_POSTER_CACHE_CONTROL = "public, max-age=604800, stale-while-revalidate=2592000"


def _public_javdb_image_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in {"tp.cmastd.com", "tp.spfcas.com"}:
        return url
    parts = parsed.path.lstrip("/").split("/")
    if len(parts) < 2 or parts[1] not in {"covers", "small_covers"}:
        return url
    return urllib.parse.urlunparse(parsed._replace(
        netloc="c0.jdbstatic.com",
        path="/" + "/".join(parts[1:]),
    ))


def _decrypt_javdb_image(data: bytes) -> bytes:
    """解码 JavDB App 图床的单字节 XOR 图片（首字节为密钥）。"""
    if len(data) < 2:
        return data
    key = data[0]
    table = bytes(key ^ i for i in range(256))
    return data[1:].translate(table)


@app.get("/api/poster-proxy")
def poster_proxy(url: str):
    cfg = config_store.load()
    if not url or not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="invalid url")
    # SSRF 防护：只允许白名单域名
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
    except Exception:
        raise HTTPException(status_code=400, detail="invalid url")
    if not any(host == d or host.endswith("." + d) for d in _ALLOWED_IMAGE_DOMAINS):
        raise HTTPException(status_code=400, detail="domain not allowed")
    javdb_headers = {
        "User-Agent": "Dart/3.5 (dart:io)",
        "Referer": cfg.javdb_api_url.rstrip("/") + "/",
    }
    is_encrypted_javdb = host == "tp.spfcas.com"

    candidates = []
    if cfg.poster_decrypt:
        # 解密模式：优先取 App 图床原图并解码为无水印 JPEG
        candidates.append((url, javdb_headers, is_encrypted_javdb))
        if is_encrypted_javdb:
            candidates.append((_public_javdb_image_url(url), javdb_headers, False))
    else:
        # 替换模式：tp.* 图床替换为公开明文 CDN（带水印）
        candidates.append((_public_javdb_image_url(url), javdb_headers, False))

    if cfg.dbo_api_url and cfg.dbo_api_key:
        candidates.append((
            f"{cfg.dbo_api_url.rstrip('/')}/api/image?url={urllib.parse.quote(url)}",
            {"X-API-Key": cfg.dbo_api_key},
            False,
        ))
    last_error = None
    for image_url, headers, decrypt in candidates:
        try:
            req = urllib.request.Request(image_url, headers=headers)
            r = urllib.request.urlopen(req, timeout=10)
            content = r.read()
            content_type = r.headers.get("Content-Type", "image/jpeg").split(";", 1)[0]
            if decrypt:
                content = _decrypt_javdb_image(content)
                if len(content) < 3 or content[:2] != b"\xff\xd8":
                    raise ValueError("decrypted poster is not a JPEG")
                content_type = "image/jpeg"
            if not content_type.startswith("image/"):
                raise ValueError(f"unexpected content type: {content_type}")
            return Response(
                content=content,
                media_type=content_type,
                headers={"Cache-Control": _POSTER_CACHE_CONTROL},
            )
        except Exception as e:
            last_error = e
    raise HTTPException(status_code=502, detail=f"image fetch failed: {last_error}")
