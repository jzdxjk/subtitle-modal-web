# 字幕云翻译 (Subtitle Cloud Translation) v2.10

> Codex 交接文档 — 日文 AV 字幕自动生成服务

## What it does

监控 115 云盘目录 → 提取音频 → GPU 云端 Whisper 转录 → LLM 翻译日→中 → 输出中文 SRT。

```
115云盘(WATCH_DIR) → Watchdog → Job Queue(SQLite) → Worker Pool(1-10)
                                                       │
                                          ┌────────────┴────────────┐
                                          ▼                         ▼
                                     ffmpeg 提音频            Modal Cloud GPU
                                     (本地,串行)             (Whisper 转录)
                                          │                         │
                                          └─────────┬───────────────┘
                                                    ▼
                                              LLM 翻译(DeepSeek)
                                                    │
                                                    ▼
                                              输出 .srt 到 /output
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web | FastAPI + uvicorn, port 8898 |
| ASR | Modal cloud GPU + [Faster-Whisper-TransWithAI-ChickenRice](https://github.com/TransWithAI/Faster-Whisper-TransWithAI-ChickenRice) |
| Translation | DeepSeek API (OpenAI compatible), `deepseek-v4-flash` |
| Storage | SQLite WAL mode (job queue) |
| Audio | ffmpeg: AAC passthrough or re-encode to 64k mono |
| Container | Python 3.10-slim, Docker |

## File Map

```
字幕云翻译/
├── app/
│   ├── main.py          # FastAPI: REST endpoints, config CRUD, poster proxy
│   ├── worker.py        # Job runner pool + watchdog + pipelined processing
│   ├── modal_runner.py  # Modal cloud bridge: clone repo, patch, launch, wait
│   ├── translator.py    # SRT parse/build + LLM batch translate (batch_size=20)
│   ├── storage.py       # SQLite job CRUD, status machine
│   ├── media.py         # AV code regex, ffmpeg audio extraction with progress
│   ├── config.py        # AppConfig dataclass, JSON file + env override
│   ├── __init__.py      # Package marker
│   └── static/          # SPA frontend (index.html, app.js, styles.css) + PWA
├── tests/
│   └── test_core.py     # Unit tests (pytest)
├── tmp/                 # DBO query utilities (not part of app, helper scripts)
├── config/
│   └── config.json      # Runtime config (Modal tokens, API keys)
├── Dockerfile
└── requirements.txt     # fastapi, uvicorn, pydantic, modal
```

## Pipeline State Machine

```
queued → [worker claims atomically] → running
                                      ├── done   (output_files populated)
                                      ├── failed (error message stored)
                                      └── cancelling → cancelled

Retry: failed/cancelled → queued (resets progress, output_files)
```

- `claim_next_queued()`: `SELECT + UPDATE` in single connection (not truly atomic across workers but single-writer SQLite WAL is enough)
- Workers auto-restart on crash
- Config refreshes every 30s, `max_workers` changes dynamically adjust semaphore

## Key Design Decisions

### Modal bridge embedded as string
`modal_runner.py` generates `modal_web_entry.py` bridge dynamically via `textwrap.dedent()`. Avoids shipping a separate entry point. The bridge:
- Patches `modal_infer.py`: injects `include_source=True` (uploads local source to cloud)
- Injects `jim-ja-transcribe` model preset (Japanese Whisper, not in upstream)
- Flow: upload audio → cloud infer → download outputs

### ffmpeg dual-path
`media.py:build_ffmpeg_command()`:
- AAC source → stream copy (zero CPU, 10-30s)
- Non-AAC → re-encode 64k mono, single thread

### Translation failure tolerance
LLM API fails for a batch → keeps original Japanese text. No data loss.

### Watchdog dedup
`SmallFileIgnoreStore`: snapshots {path → [file size+mtime]} for undersized files. Re-scans only when files actually change.

### Config merge order
`AppConfig.merged_with_env()`: file config.json < env vars (env always wins for secrets)

## Setup

```bash
cd subtitle-modal-web/字幕云翻译
docker build -t jzdxjk/subtitle-modal-web:dev .
docker compose up -d
```

**Required env:**
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`
- `HF_TOKEN` (optional, HuggingFace model download)
- `WATCH_DIR` → monitored directory
- `OUTPUT_DIR` → .srt output location

**Config:** Web UI at `http://host:8898` → Settings, or direct `config/config.json`.

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | SPA frontend |
| `POST` | `/api/jobs` | Create job `{input_path, output_dir, formats, overwrite, move_target_dir}` |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/{id}` | Job detail (status, progress, output_files, timings) |
| `POST` | `/api/jobs/{id}/cancel` | Cancel queued/running |
| `POST` | `/api/jobs/{id}/retry` | Retry failed |
| `POST` | `/api/jobs/retry-failed` | Batch retry all failed |
| `DELETE` | `/api/jobs/{id}` | Delete job |
| `GET/POST` | `/api/config` | Read/update config (secrets redacted in GET) |
| `POST` | `/api/transcribe-config` | Update transcribe settings only |
| `POST` | `/api/transcribe/models` | Proxy fetch OpenAI model list |
| `POST` | `/api/transcribe/test` | Test API connectivity |
| `GET` | `/api/dbo-search?q=&limit=` | Search avdb |
| `GET` | `/api/poster-proxy?url=` | Proxy image through DBO |
| `GET` | `/api/pack?date=` | Download day's subtitles as zip |
| `GET` | `/api/version` | `{"version": "v2.10"}` |
| `POST` | `/api/clear-audio-cache` | Delete cached audio files |

## Known Issues / Tech Debt

1. **Embedded bridge script** — `_write_bridge_script()` is 300 lines of Python in a string. Hard to debug/version. Should be standalone `.py`.
2. **`_process_job_pipelined`** — 200+ line method mixing serial/parallel coordination + progress. Refactor candidate.
3. **`claim_next_queued()`** — Not atomic under concurrent access. Fine for single-process, fragile if multi-process.
4. **Progress update contention** — SQLite WAL writes every few seconds per worker. Batch progress updates.
5. **Cancel doesn't kill cloud** — Cancelling a running job stops waiting but Modal cloud job keeps running.
6. **Repo branch fragility** — Bridge patches `modal_infer.py` and injects `jim-ja-transcribe`. Breaks if upstream changes the class structure.
7. **`cloudflare_asr.py` / `groq_asr.py` / `deepseek_translate.py`** — Pycache has references to these modules but no source files exist. Dead code or deleted modules whose .pyc lingered.
