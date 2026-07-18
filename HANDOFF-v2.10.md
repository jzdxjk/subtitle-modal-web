# 字幕云翻译 — 项目交接文档

> 最后更新: 2026-07-05
> 当前版本: v2.10
> 交接对象: NAS Agent

---

## 1. 项目概述

**一句话**: NAS Docker Web 控制台，自动将视频/音频文件上传到 Modal 云端 GPU 做 Whisper 字幕识别（日语→中文翻译），字幕回存本地，带海报墙画廊和 DBO 番号搜索。

**核心流程**:
```
NAS 监控目录 → ffmpeg 抽音频 → Modal 云端 GPU 推理 → 字幕归档 → Web 展示
```

- **Web UI**: FastAPI + vanilla JS SPA，端口 8898
- **任务队列**: SQLite (WAL 模式)，支持并发、重试、取消
- **云端推理**: Modal (GPU)，使用 TransWithAI/Faster-Whisper-TransWithAI-ChickenRice
- **目标场景**: AV 字幕批量处理，按完成日期分组海报墙

---

## 2. 技术架构

```
┌──────────────────────────────────────────────────┐
│  NAS (Docker)                                     │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ main.py  │  │ worker.py│  │ modal_runner.py│  │
│  │ (FastAPI)│  │(asyncio) │  │ (git clone repo │  │
│  │          │  │          │  │  + bridge script│  │
│  └────┬─────┘  └────┬─────┘  │  → Modal Cloud)│  │
│       │             │         └───────┬────────┘  │
│  ┌────┴─────────────┴─────────────────┴──────┐    │
│  │  storage.py (SQLite)  │  media.py (ffmpeg)│    │
│  └───────────────────────────────────────────┘    │
│                     ↕ gRPC/HTTP                    │
│  ┌──────────────────────────────────────────────┐ │
│  │  Modal Cloud (GPU)                            │ │
│  │  infer.py + modal_infer.py                    │ │
│  │  Faster-Whisper + ChickenRice 模型             │ │
│  │  VAD 语音检测 → 识别 → SRT 输出                │ │
│  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

### 两种工作模式

| 模式 | 条件 | 云端任务 | 输出 |
|------|------|---------|------|
| **翻译** (默认) | `enable_transcribe=False` | `task: translate`，Whisper 直接日→中 | 中文 SRT |
| **转录** | `enable_transcribe=True` + OpenAI 配置完整 | `task: transcribe`，Whisper 日→日原文 → LLM 翻中文 | 中文 SRT + `/ja_subs/` 存日文原文 |

---

## 3. 目录结构

```
字幕云翻译/
├── app/
│   ├── main.py              # FastAPI 入口，API 路由
│   ├── worker.py            # 任务执行引擎 (asyncio + JobRunner)
│   ├── modal_runner.py      # Modal 云端桥接 (git clone repo + bridge script)
│   ├── storage.py           # SQLite 任务持久化
│   ├── media.py             # ffmpeg 抽音频，番号提取
│   ├── translator.py        # LLM 翻译模块 (OpenAI 兼容 API)
│   ├── config.py            # 配置数据类 + env merge
│   └── static/
│       ├── index.html       # SPA 入口
│       ├── app.js           # 前端主逻辑 (~30KB)
│       ├── styles.css       # 样式
│       ├── sw.js            # PWA Service Worker
│       └── manifest.json    # PWA manifest
├── config/
│   ├── config.json          # 运行时配置 (Web UI 修改后持久化)
│   └── jobs.sqlite3         # 任务数据库
├── cache/
│   └── modal-repo/          # 克隆的 ChickenRice 仓库 (运行中自动维护)
├── docker-compose.yml       # 主实例
├── docker-compose.temp-second-instance.yml  # 临时测试实例
├── Dockerfile
├── requirements.txt
├── tests/
│   └── test_core.py         # 单元测试
├── HANDOFF.md               # 旧交接文档 (v2.9)
├── DBO_API_DOC.md           # DBO API 文档
└── README.md
```

---

## 4. 关键文件职责

### `app/config.py` — 配置中心
```python
@dataclass
class AppConfig:
    # Modal 凭证
    modal_token_id: str = ""
    modal_token_secret: str = ""
    hf_token: str = ""

    # GPU / 模型
    default_gpu: str = "T4"
    default_model: str = "chickenrice"

    # 路径
    default_output_dir: str = "/output"
    default_cache_dir: str = "/cache"

    # 云端仓库
    repo_url: str = "https://github.com/TransWithAI/Faster-Whisper-TransWithAI-ChickenRice.git"
    repo_branch: str = "bec3d22"           # 锁定 v1.7，避免 v1.10 VAD 性能回归

    # 转录模式
    enable_transcribe: bool = False
    openai_api_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    transcribe_prompt: str = "..."
    transcribe_model: str = "jim-ja-transcribe"

    # DBO 海报搜索
    dbo_api_url: str = ""
    dbo_api_key: str = ""

    # Watchdog
    enable_watchdog: bool = False
    watchdog_interval_seconds: int = 60
    min_file_size_mb: int = 100
    max_workers: int = 1

    def merged_with_env(self) -> "AppConfig":
        # 环境变量可以覆盖配置值，优先级: env > config.json > 默认值
```

- 环境变量映射: `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `HF_TOKEN`, `REPO_BRANCH` 等
- 持久化路径: `{CONFIG_DIR}/config.json`
- 完整列表见 `config.py` 中的 `env_map`

### `app/modal_runner.py` — 云端桥接 (最关键)
**工作流程**:
1. `_ensure_repo(work_dir)`: git clone/fetch ChickenRice 仓库到 `cache/modal-repo/`
   - 统一使用 `git fetch` + `git reset --hard FETCH_HEAD`，兼容 branch/tag/commit hash
   - fetch 结果缓存 1 小时避免频繁拉取
2. `_patch_modal_infer(work_dir)`: 给 `modal_infer.py` 的 `modal.App()` 注入 `include_source=True`
3. `_write_bridge_script(repo_dir)`: 生成临时代理脚本 `modal_web_entry.py`，桥接 Modal 函数
4. `launch()`: 启动 `subprocess.Popen` 执行桥接脚本
5. `ModalRunHandle`: 管理异步云任务生命周期

**桥接脚本关键逻辑** (内嵌在 `_write_bridge_script` 中):
- 导入 repo 中的 `modal_infer` 模块
- 自动注入 `jim-ja-transcribe` 模型预设（兼容旧版 ChickenRice）
- 构建 `UserSelection` → `upload_single_file` → `build_job_payload` → `run_remote_pipeline`
- 最后 `download_outputs` 取回结果

### `app/worker.py` — 任务执行
**核心**: `JobRunner` + asyncio 并发

`_process_job_pipelined(job)` 的执行阶段:
1. **本地阶段** (串行，`asyncio.Lock`): ffmpeg 抽音频 → Modal 上传 → 提交
2. **云端阶段** (并行): 等待 Modal 推理完成
3. **后处理**: `_normalize_outputs` 文件名规范化
4. **转录后处理** (如果 `is_transcribe=True`): 保存日文到 `/ja_subs/` → LLM 翻译

Watchdog: 定时扫描 `WATCH_DIR`，自动发现新文件创建任务。

### `app/translator.py` — LLM 翻译
- 解析 SRT → 分批调用 OpenAI 兼容 API → 重建 SRT
- 批次大小: 20 条/次
- 分隔符: `---`
- 失败回退: 保留原文

### `app/media.py` — 媒体处理
- `extract_av_code()`: 正则提取 AV 番号 (如 `FNS-192`, `FC2-PPV-4907804`)
- `prepare_audio()`: ffmpeg 提取音频，支持进度回调
- `output_subtitle_path()`: 生成字幕输出路径

### `app/storage.py` — SQLite 任务存储
- 表: `jobs` (id, input_path, output_dir, formats, overwrite, move_target_dir, status, message, output_files, timestamps, progress)
- 状态机: `queued → running → done/failed/cancelled`
- 支持: `claim_next_queued`, `is_cancelling`, `retry_job`, `delete_job`, `get_by_completion_date`

---

## 5. API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | SPA 入口 |
| GET | `/api/version` | 版本号 (v2.10) |
| GET/POST | `/api/config` | 读取/保存全局配置 |
| POST | `/api/transcribe-config` | 仅保存转录相关配置 |
| POST | `/api/transcribe/models` | 获取 OpenAI 模型列表 (代理) |
| POST | `/api/transcribe/test` | 测试 OpenAI 连通性 |
| POST | `/api/jobs` | 创建任务 |
| GET | `/api/jobs` | 列出所有任务 (无分页) |
| GET | `/api/jobs/{id}` | 单个任务详情 |
| POST | `/api/jobs/{id}/retry` | 重试失败任务 |
| POST | `/api/jobs/retry-failed` | 批量重试所有失败任务 |
| POST | `/api/jobs/{id}/cancel` | 取消任务 |
| DELETE | `/api/jobs/{id}` | 删除任务 |
| GET | `/api/dbo-search` | DBO 番号搜索代理 |
| POST | `/api/test-dbo` | 测试 DBO 连通性 |
| GET | `/api/poster-proxy` | 图片代理 (SSRF 白名单防护) |
| GET | `/api/pack` | 打包某天字幕为 ZIP |
| POST | `/api/clear-audio-cache` | 清空音频缓存 |

---

## 6. 配置项速查

### docker-compose.yml 挂载点
| 容器内路径 | 宿主目录 | 用途 |
|-----------|---------|------|
| `/watch` (ro) | CD2/115 视频目录 | 视频源 |
| `/output` | 字幕输出目录 | 生成的 SRT |
| `/cache` | NAS 本地缓存 | 音频临时文件 + repo clone |
| `/config` | 配置目录 | config.json + jobs.sqlite3 |

### 环境变量
| 变量 | 必填 | 说明 |
|------|------|------|
| `MODAL_TOKEN_ID` | ✅ | Modal API Token ID |
| `MODAL_TOKEN_SECRET` | ✅ | Modal API Token Secret |
| `HF_TOKEN` | 否 | HuggingFace Token (私有模型) |
| `REPO_BRANCH` | 否 | ChickenRice 仓库分支，默认 `bec3d22` (v1.7) |
| `WATCH_DIR` | 否 | 监控目录，默认 `/mnt/media` |

---

## 7. 已修复问题 (v2.10 → v2.11)

### 问题 1: 转录模式云端返回简中而非日文原文
**根因**: v1.10 的 `modal_infer.py` 构建 infer 命令时未传递 `--task` 参数，导致 `generation_config.json5` 的 `task: translate` 生效。
**修复**: 回退到 v1.7 (commit `bec3d22`)，该版本正确传递 `--task` 参数。

### 问题 2: 云端推理极慢 (VAD 性能回归)
**根因**: v1.10 (commit `6210488`) 的 VAD 处理从 1 次 528 chunks 拆成 593 次独立 1/1 chunks，每次都重新初始化模型。
**修复**: 同上，回退到 v1.7。

### 问题 3: `_ensure_repo` 不兼容 commit hash
**根因**: `git clone --branch <hash>` 不支持纯 commit hash，`git checkout <hash>` 后 `git pull --ff-only` 也会失败。
**修复**: 改为统一使用 `git fetch` + `git reset --hard FETCH_HEAD`。

### 改动文件清单
| 文件 | 改动 |
|------|------|
| `app/config.py:27` | `repo_branch: str = "bec3d22"` |
| `config/config.json` | `"repo_branch": "bec3d22"` |
| `docker-compose.yml:21` | `REPO_BRANCH: "bec3d22"` |
| `docker-compose.temp-second-instance.yml:22` | `REPO_BRANCH: "bec3d22"` |
| `app/modal_runner.py:209-225` | `_ensure_repo` 改为 fetch+reset 模式 |

---

## 8. 部署与运维

### 初次部署
```bash
# 1. 配置 .env 文件
cp .env.example .env
# 编辑 .env: 填入 MODAL_TOKEN_ID, MODAL_TOKEN_SECRET

# 2. 修改 docker-compose.yml 挂载路径
#    /watch → 视频目录
#    /output → 字幕输出目录
#    /cache → 缓存目录 (建议不要放在网盘挂载上)
#    /config → 配置目录

# 3. 启动
docker compose up -d --build

# 4. 访问 http://NAS_IP:8898
```

### 已部署的实例信息
- 主实例端口: `8898`
- 临时测试实例端口: `9600` (通过 `docker-compose.temp-second-instance.yml`)
- 当前运行容器: `subtitle-modal-web`

### 常用运维命令
```bash
# 查看日志
docker logs -f subtitle-modal-web

# 重启
docker compose restart

# 清除缓存 (需要重置 repo — 比如修复后验证 fresh clone)
rm -rf ./cache/modal-repo

# 清空音频缓存
curl -X POST http://localhost:8898/api/clear-audio-cache

# 临时测试实例
docker compose --env-file .env.temp-second-instance -f docker-compose.temp-second-instance.yml up -d --build
docker compose --env-file .env.temp-second-instance -f docker-compose.temp-second-instance.yml down
```

### 健康检查
```bash
curl http://localhost:8898/api/version   # → {"version":"v2.10"}
curl http://localhost:8898/api/config    # → 当前配置 (已脱敏)
```

---

## 9. 修复验证方法

修改后重启容器，检查以下内容:

### VAD 性能
云端日志中 VAD 输出应为一次性的批量处理:
```
VAD Progress: 528/528 chunks (100.0%) on CPU
```
而不是 593 次独立:
```
VAD Progress: 1/1 chunks (100.0%) on CPU   (x593)
```

### 转录模式 `--task` 参数
云端日志中 `Arguments` 应包含 `'task': 'transcribe'` 或 `'task': 'translate'`，而非 `'task': None`:
```
Arguments: {..., 'task': 'transcribe', ...}
```

### Fresh clone 兼容性
```bash
rm -rf ./cache/modal-repo
# 重启容器或触发一次任务，应能正常 clone + checkout bec3d22
```

---

## 10. 测试

```bash
# 运行单元测试
cd 字幕云翻译
python -m pytest tests/test_core.py -v
```

测试覆盖: AV 番号提取、FC2 番号规范化、SRT 解析、配置合并、文件过滤等。

---

## 11. 技术债与风险

- **前端 app.js 30KB 单文件**: 建议后续拆分为 api.js / jobs.js / poster.js / ui.js
- **API 无分页**: `/api/jobs` 全量返回，任务量上千后性能会下降
- **API 无认证**: 所有端点匿名访问，如暴露公网需加鉴权
- **Docker root 用户**: 建议添加非 root 用户
- **PWA 缓存**: 每次修改静态资源需递增 `sw.js` 的 CACHE 版本名 + `index.html` 的 `?v=` 参数
- **镜像推送**: `jzdxjk/subtitle-modal-web:v2.7` 已推送 Docker Hub，但后续版本可能未推送

---

## 12. 关键参考资料

- ChickenRice 仓库: https://github.com/TransWithAI/Faster-Whisper-TransWithAI-ChickenRice
- 锁定 commit: `bec3d22` (v1.7，稳定可用)
- 问题 commit: `6210488` (v1.10，VAD 性能回归 + --task 缺失)
- Modal 文档: https://modal.com/docs
- DBO API 文档: 见项目内 `DBO_API_DOC.md`
- 旧交接文档: `HANDOFF.md` (v2.9, 含完整历史变更记录)
