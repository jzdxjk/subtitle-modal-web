# HANDOFF - 字幕云翻译（subtitle-modal-web）

## Re-entry Sentence（下次开工先贴这句）

`C:\Users\jzdxjk\Documents\字幕云翻译\HANDOFF.md` — 全部消息中文化 + 实时进度条 + 阶段耗时 + 5 标签页分页（运行中/排队中/失败/已完成/已取消）+ 重试/批量重试 + FIFO 排队排序 + 取消按钮 + 前端反馈提示；win 预览端口 15678。

---

## 1) 项目目标
- 在 NAS / Docker 上运行字幕任务中台：
  - 本地负责扫描媒体、抽音频、任务队列、结果落盘。
  - Modal 云端负责推理。
- 模型仓库：`TransWithAI/Faster-Whisper-TransWithAI-ChickenRice`
- 分支：`v1.7`
- 默认模型：`chickenrice`

---

## 2) 当前工作区与运行信息
- 本地目录：`C:\Users\jzdxjk\Documents\字幕云翻译`
- 容器名：`subtitle-modal-web`
- NAS 路径：`/tmp/zfsv3/nvme14/17858927371/data/Docker/subtitle-modal-web/`
- Docker 端口映射：`8898:8898`
- 本地预览端口：`15678`

---

## 3) 全部改动记录

### 3.1 Bug 修复 — 脏文件名残留
- **文件**：`app/worker.py` — `_normalize_outputs()`
- **问题**：`by_suffix = {suffix: path}` 字典在多个同后缀文件时只保留最后一个，脏文件（如 `489155.com@START-554-xxxx.srt`）不被清理
- **修复**：改为 `by_suffix: dict[str, list[Path]]` 分组列表 → 优先匹配目标文件名 → 清理剩余脏文件

### 3.2 中文国际化
| 文件 | 内容 |
|---|---|
| `app/storage.py` | `等待中` / `用户已取消` / `取消中...` / 重试消息中文化 |
| `app/worker.py` | 全部 stage 提示改为中文 + emoji（🎵 ☁️ 🧠 📦 ✅ ❌ ⏭️） |

### 3.3 实时进度条 + 阶段耗时

**后端**：
- `app/media.py` — `prepare_audio` 新增 `on_progress` 回调；`subprocess.Popen` + 线程解析 ffmpeg 的 `Duration:` / `time=` 行 → 计算百分比
- `app/worker.py` — `_process_job_pipelined` 记录 `phase_timings`（local / cloud），写入 `started_at / completed_at / progress` 到 DB

**前端**：
- 进度条（`app/static/styles.css`）— 8px 高圆角，分段彩色：
  - 本地阶段 0-35%：橙色渐变
  - 云端阶段 40-90%：蓝色渐变
  - 完成阶段 90-100%：绿色渐变
- 运行中实时显示 `⏱ 已运行 XXs`

### 3.4 5 标签页 + 分页 + 排序

**标签定义**（`app/static/app.js`）：

| 标签 | 包含状态 | 排序 |
|---|---|---|
| 运行中 | `running` | `started_at` 升序（先开始的在上） |
| 排队中 | `queued` | `created_at` 升序（最早提交的在上，FIFO） |
| 失败任务 | `failed` | API 返回顺序（最新在前） |
| 已完成 | `done` | API 返回顺序 |
| 已取消 | `cancelled`, `cancelling` | API 返回顺序 |

- 每页 5 条，带上下翻页
- 标签页上显示数量：`运行中 (2)`

### 3.5 重试机制

| API | 方法 | 路径 |
|---|---|---|
| 单条重试 | POST | `/api/jobs/{id}/retry` |
| 批量重试全部失败 | POST | `/api/jobs/retry-failed` |

- 支持 `failed / cancelled / cancelling` 三种状态重试
- 重试后重置：`status=queued`, `output_files=[]`, `started_at=0`, `completed_at=0`, `progress=0`
- 失败标签页顶部有「一键重试全部失败」按钮

### 3.6 UI 细节优化
- 取消按钮文字从 `停止` 改为 `取消`，与后端统一
- 已取消任务显示 `取消时间 HH:MM:SS`（而不是 `完成时间`）
- 保存配置后提示 `✅ 保存配置成功！`
- 提交任务后提示 `✅ 加入队列成功！`
- 耗时格式 `mm:ss`（如 `总耗时21:15`）

### 3.7 数据库新增字段（`app/storage.py`）

```python
started_at: float = 0.0     # 开始处理时间戳
completed_at: float = 0.0   # 完成/失败/取消时间戳
progress: int = 0            # 0-100 进度
```

新增迁移：`ALTER TABLE jobs ADD COLUMN ...`

### 3.8 单元测试补充（`tests/test_core.py`）
- `test_retry_failed_job`
- `test_retry_all_failed_jobs`
- `test_retry_cancelled_job`
- `test_cannot_retry_non_failed_job`

---

## 4) 关键文件清单

| 文件 | 职责 |
|---|---|
| `app/main.py` | FastAPI 路由（config / jobs / cancel / retry / retry-failed） |
| `app/config.py` | AppConfig + ConfigStore（JSON + env 覆盖） |
| `app/storage.py` | Job dataclass + SQLite WAL 存储、重试逻辑 |
| `app/worker.py` | Worker 池、流水线（ffmpeg→上传→云端）、进度/计时/中文消息 |
| `app/media.py` | 媒体发现、AV 码提取、ffmpeg 进度解析 |
| `app/modal_runner.py` | Modal 桥接（repo 管理、patch、Popen 管线） |
| `app/static/index.html` | 5 标签页结构 + 失败工具条 |
| `app/static/app.js` | 标签渲染、分页、排序、进度条、重试/取消交互 |
| `app/static/styles.css` | 分段彩色进度条、标签页、重试按钮、工具条 |
| `tests/test_core.py` | 单元测试（config / media / store / retry / modal） |
| `docker-compose.yml` | 服务定义 + 挂载 + 环境变量（含密钥⚠️） |
| `Dockerfile` | python:3.10-slim + ffmpeg + git |
| `requirements.txt` | fastapi / uvicorn / pydantic / modal |

---

## 5) API 总览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/config` | 获取配置（脱敏） |
| POST | `/api/config` | 保存配置 |
| POST | `/api/jobs` | 创建任务 |
| GET | `/api/jobs` | 列出所有任务（按 created_at DESC） |
| GET | `/api/jobs/{id}` | 任务详情 |
| POST | `/api/jobs/{id}/cancel` | 取消任务（queued→cancelled / running→cancelling） |
| POST | `/api/jobs/{id}/retry` | 重试（failed/cancelled/cancelling→queued） |
| POST | `/api/jobs/retry-failed` | 批量重试所有 failed 任务 |

---

## 6) 本地预览

```powershell
cd "C:\Users\jzdxjk\Documents\字幕云翻译"
pip install fastapi uvicorn pydantic
python -c "import os;os.chdir('.');os.environ['CONFIG_DIR']='.';os.environ['CACHE_DIR']='./cache';os.environ['WATCH_DIR']='.';os.environ['OUTPUT_DIR']='./output';import uvicorn;uvicorn.run('app.main:app',host='127.0.0.1',port=15678)"
```

打开 `http://127.0.0.1:15678`

---

## 7) NAS 部署

```bash
# Windows → NAS 传代码
scp -r "C:\Users\jzdxjk\Documents\字幕云翻译\app" root@<NAS_IP>:/tmp/zfsv3/nvme14/17858927371/data/Docker/subtitle-modal-web/app/

# NAS 重建
cd /tmp/zfsv3/nvme14/17858927371/data/Docker/subtitle-modal-web
docker-compose down && docker-compose build --pull && docker-compose up -d
sleep 10 && docker logs subtitle-modal-web --tail 20
```

---

## 8) 已知注意事项

1. **docker-compose.yml 含明文密钥**（MODAL_TOKEN_ID / MODAL_TOKEN_SECRET / HF_TOKEN），建议部署到 NAS 后改用 `.env` 文件
2. 当前项目目录**不是 git 仓库**，无法 `git diff`
3. 历史任务不会自动获得新字段（`started_at / completed_at / progress`），新提交/执行的才会
4. ffmpeg 进度解析依赖 stderr 中的 `Duration:` / `time=` 行，某些 ffmpeg 版本输出格式差异可能影响解析

---

## 9) 快速排障命令

```bash
# 容器日志
docker logs --tail 200 subtitle-modal-web

# 查看任务状态
docker exec -it subtitle-modal-web sh -c "sqlite3 /config/jobs.sqlite3 'SELECT id,status,substr(message,1,80),progress FROM jobs ORDER BY created_at DESC LIMIT 20'"
```

---

## 10) 下次可做的方向

1. 优化 ffmpeg 进度条实时刷新频率（当前只在上报百分比变化时更新，可考虑秒级定时）
2. 给重试增加确认弹窗（尤其批量重试）
3. 为新 API 增加 FastAPI 层集成测试
4. 清理 `styles.css` 压缩格式（当前部分样式被合并到单行，可读性差）
5. 任务卡片增加展开/折叠详情
6. 已完成任务支持删除
