# HANDOFF - 字幕云翻译（subtitle-modal-web）

## Re-entry Sentence（下次开工先贴这句）

`C:\Users\jzdxjk\Documents\字幕云翻译\HANDOFF.md` — 暗色 NAS 风 UI + Mac Dock 式 4 视图导航 + 主界面 Emby 风格横版海报墙（按日期分组 + 横向滚动行）+ 海报后端代理 + localStorage 持久化缓存 + 增量渲染 + 亮/暗主题 + PWA 移动端底部 Dock 重做 + Docker Hub 发布 + Cloudflare 探索（已回滚）+ 取消杀进程 + 失败不重试 + 保存 toast + 版本号 + 番号规范化搜索回退 + 根目录直放文件迁移修复；win 预览端口 15678；v2.3 刚修完根目录直放文件迁移 bug；下一步 → LLM 翻译模块。

---

## 版本迭代

### v1.0 — 基础功能（3.1~3.8）
- FastAPI 后端，SQLite 存任务状态
- Modal 云端推理桥接
- ffmpeg 音频抽取
- 任务创建/队列/取消/重试

### v1.1 — UI 大改（3.9）
- Dock 210px 左栏桌面端导航
- 4 视图 SPA：主界面 / 任务队列 / 提交任务 / 配置
- Manrope + Noto Sans SC 字体
- CSS 变量双主题（亮/暗），localStorage 记忆
- 启动 Splash 动画
- PWA manifest + Service Worker

### v1.2 — 海报墙（3.10）
- dbo API 代理 JavDB 封面搜索
- 封面图 800×536 横版，3:2 容器
- 串行请求队列 + 防重复并发
- poster-proxy 后端代理（手机公网可用）
- localStorage 持久化海报缓存

### v1.3 — 日期分组画廊
- 按完成日期分组（今天/昨天/MM月DD日/YYYY-MM-DD）
- 每组独立横向滚动行
- 入场动画（首次加载播 fadeUp，后续刷新跳过）

### v1.4 — 移动端优化
- 底部 Dock 重做：72px 高，桌面端风格纯色背景，11px 文字，蓝色激活高亮
- 画廊卡片响应式：桌面 240px，移动端 `50vw - 18px`
- 主题按钮加「主题」文字标签

### v2.3 — 根目录直放文件迁移修复（2026-05-26）

- **bug**：媒体文件直接放在 watch 根目录（如 `/watch/ABC-123.mp4`）而非子文件夹时，任务结束后 `shutil.move` 会把整个 `/watch` 目录移到输出目录
- **根因**：`media_path.parent` 是 watch_root 本身，迁移逻辑未做守卫
- **修复（worker.py）**：
  - watchdog 循环：根目录直放文件 → 自动创建以番号命名的子目录 → 移入文件 → 统一走子目录模式
  - 迁移安全守卫：`parent == self.watch_root` 时跳过并 warning，永不移动 watch 根目录
- **修复（app.js）**：
  - 画廊 av 名称去扩展名：`ABC-123.mp4` → `ABC-123`（正则 strip 常见视频扩展名）
  - 海报搜索去扩展名：`loadPoster()` 内先 strip 再搜 DBO
- **副作用修复**：reasonix 写入的 Python 文件带 UTF-8 BOM，导致语法错误，已批量清除

### v2.2.2 — 番号规范化：海报搜索回退 + 失败自动重试
- **核心修复**：素人番号（如 `300Mium-1336`）提取后规范化为 DBO 认识的形式（`mium-1336`）回退搜索
- `AV_PATTERN` 正则加 `(?:\d+)?` 可选数字前缀 + `re.IGNORECASE` 支持混合大小写
- 新增 `normalize_av_code()`（Python）+ `_normalizeAvCode()`（JS）规范化函数
- 前端 `_doFetch()` 先搜原始码，无结果自动用规范化码再搜一次（最多 2 次请求）
- 页面刷新时自动重试之前搜不到海报的番号（localStorage 过滤 `"null"` 缓存值）
- Service Worker 改为 network-first 策略（HTML/CSS/JS），更新不再被旧缓存卡住

### v2.2.1 — hotfix: json import
- `/api/dbo-search` 和 `/api/test-dbo` 中用了 `json.dumps()` 但顶层没 `import json`，修复

### v2.2 — DBO 搜索代理 + 诊断工具
- **核心修复**：DBO 搜索从前端直连改为后端代理（`/api/dbo-search`）
- 根因：`app.js` 中 `_doFetch()` 直连 `10.0.0.235:9090`，切换流量后浏览器访问不了内网
- 之前只修了图片代理（`poster-proxy`），搜索那路一直是裸连，不是回归
- 新增 `/api/test-dbo` 诊断端点 + 配置页「测试 DBO 连通性」按钮

### v2.1 — Cloudflare+DeepSeek 尝试（已回滚）
- 新增 `app/cloudflare_asr.py` + `app/deepseek_translate.py`（已删除）
- 配置页 ASR 提供商切换 + CF 密钥 + LLM 配置区域
- 取消即杀 ffmpeg（`proc.kill()` in reader thread，保留）
- 失败/取消不自动重试（`has_any_failed_job_for_path`，保留）
- 保存成功 toast 通知（保留）
- 版本号显示 `v2.1`（保留）
- **回滚原因**：Cloudflare Workers AI 限制 5MB/请求，2h 视频需切片 5-6 段，每天 100 次额度只够 16-20 部；NAS 上 ffmpeg 的 libopus / segment_size 均不支持。改为探索 LLM 翻译方案。

### v1.9 — 安全加固 + 更多修复
- SSRF 防护：poster-proxy 加域名白名单 + https 强制
- ffmpeg stdout 管道死锁修复：`stdout=DEVNULL`
- Modal runner stderr 管道死锁修复：加 stderr reader 线程
- 任务删除：新增 `DELETE /api/jobs/{id}` + 前端删除按钮
- 海报骨架屏：shimmer 加载动画替代空黑块
- 看门狗异常日志：`except: pass` → `logger.exception`
- 配置保存竞态提示：保存按钮下加 ⚠ 多标签页警告
- FC2 番号适配：`AV_PATTERN` 扩展匹配 `FC2-PPV-1234567`
- 海报并行加载：串行队列 → 并发 4

### v1.8 — 防重复任务提交
- 看门狗：字幕已存在则跳过，不再重复创建任务
- API：相同路径有活跃任务时返回 409 拒绝
- `_output_exists_for_media()` 辅助函数检查所有格式字幕

### v1.7 — 音频清理 + 队列页按钮优化
- 任务完成后自动删除 `cache/audio/` 中的音频缓存
- 任务队列页添「清除音频缓存」按钮（红色强调），一键清空 audio 目录
- 后端 `POST /api/clear-audio-cache` 端点
- 刷新按钮和清除按钮紧靠排列，`.header-actions` 容器 + `.btn-danger` 样式

### v1.6 — 一键打包 + 滚动修复 + 轮询优化
- 画廊每个日期分组加「打包(N)」按钮，自动 zip 当天所有字幕下载
- 后端 `/api/pack?date=ts` 端点，`JobStore.get_by_completion_date()` 查询
- 轮询加变化检测：只有任务状态、进度、完成时间变化时才重建画廊，空闲不闪
- 画廊重建时保存/恢复各日期行的横向滚动位置

### v1.5.1 — DBO 配置保存修复
- `ConfigPayload` 缺失 `dbo_api_url` / `dbo_api_key` → POST 时被 pydantic 丢弃
- `switchView("config")` 加 `loadConfig()` 调用，切回配置页自动刷新表单

### v1.5 — 净化发布
- docker-compose.yml 去明文 token → 环境变量占位符
- 去个人 NAS 路径 → 相对路径 / 通用示例
- `.env.example` 模板
- Docker Hub 发布：`jzdxjk/subtitle-modal-web:latest`
- GitHub 介绍页：`https://github.com/jzdxjk/subtitle-modal-web`

---

## 后续待推进

> **2026-05-25**：分析了 `aexachao/nas-submaster` 的架构，确定未来 3 个借鉴方向（详见下方《开发日志》）。

---

## 开发日志 — 下一步方向

### v2.2：LLM 翻译模块（借鉴点 1）

**目标**：ASR 出日文 SRT → LLM 翻译 → 中文 SRT。不再依赖 Modal ChickenRice 内置翻译。

**融入方式**：

```
现流程：ffmpeg → Modal ASR → SRT → 完成
融入后：ffmpeg → Modal ASR → SRT → [可选] LLM 批量翻译 → .zh.srt → 完成
```

**新增 `app/services/translator.py`**：
- 统一 OpenAI 兼容客户端（一份代码调 DeepSeek / Ollama / Gemini / OpenAI / 自定义）
- 分段批处理：SRT 按 N 行分组，加前后上下文防断句
- JSON 强制输出：Prompt 要求 `[{"line":1,"text":"..."}]`，解析时格式校验 + 行号对齐
- 重试 + 降级：最多 3 次，截断时自动对半分批递归处理
- 8 渠道预设（参考 nas-submaster）：DeepSeek / Ollama / Gemini / Moonshot / 通义千问 / 智谱 / OpenAI / 自定义

**新增配置项**（配置页加"翻译设置"区）：

```
翻译引擎:    [关闭 ▼] [DeepSeek ▼] [Ollama ▼] [OpenAI ▼] [自定义 ▼]
API Key:     [sk-xxx________________]
API 地址:    [https://api.deepseek.com/v1]
模型:        [deepseek-chat__________]
提示词:      [日文→中文口语化，保留格式…]
每批行数:    [15]
```

- 选"关闭"→ 不走翻译，跟现在完全一样
- 选具体渠道 → 预填默认 base_url + 模型名
- 每个渠道旁加「测试」按钮，10s 测连通延迟

**改动文件**：
| 文件 | 改动 |
|---|---|
| `app/services/translator.py` | **新建**，核心翻译模块 |
| `app/worker.py` | ASR 完成后加 `if config.llm_enabled: translate_srt()` |
| `app/config.py` | 加 llm_provider / llm_api_key / llm_api_url / llm_model / llm_prompt / llm_batch_size |
| `app/main.py` | ConfigPayload 加对应字段 + `/api/test-llm` 端点 |
| `app/static/index.html` | 配置页加翻译区 + 测试按钮 |
| `app/static/app.js` | 测试按钮逻辑 + 渠道切换预填 |

---

### v2.3：配置变更检测（借鉴点 3）

**目标**：`save()` 时先 `deepcopy` 对比新旧，相同就跳过磁盘写入。

**代码变更**（`config.py` 约 3 行）：
```python
# 在 ConfigStore 加字段
_last_saved: dict | None = None

# 在 save() 开头
new_dict = {**current, **filtered_payload}
if new_dict == self._last_saved:
    return AppConfig(**new_dict)  # 跳过写入
self._last_saved = deepcopy(new_dict)
```

**价值**：当前 `save()` 只在用户手动点按钮时触发，次数少。但后续如果加 WebSocket 配置推送或轮询自动保存，能避免大量冗余写入。

---

### v2.4：模块化 5 层架构（借鉴点 5）

**目标**：把当前扁平文件结构 → 清晰分层，长期易维护。

**目标结构**：
```
app/
├── api/                 ← 路由层（从 main.py 拆）
│   └── main.py          → 只放 @app.route + FastAPI 配置
├── core/                ← 业务层
│   ├── config.py        → AppConfig + ConfigStore
│   ├── worker.py        → JobRunner + Worker 池
│   └── models.py        → 所有 Pydantic 数据类集中
├── services/            ← 服务层（可独立调用）
│   ├── media.py           → ffmpeg 音频提取
│   ├── modal_runner.py    → Modal 云桥接
│   └── translator.py      → [v2.2 新建] LLM 翻译
├── database/            ← 数据层（从 storage.py 拆）
│   ├── connection.py      → SQLite 连接 + WAL
│   └── job_dao.py         → 任务 CRUD
├── static/              ← 前端（不动）
└── __init__.py
```

**收益**：
| | 改前 | 改后 |
|---|---|---|
| `main.py` | 路由 + 端点 + JSON 序列化混一起 | 只放路由，~150 行 |
| 加新功能 | 在 `worker.py` 里堆代码 → 越来越长 | 加 `services/xxx.py`，独立 |
| 测试 | 难测，函数分散 | 每层可单独 mock 测试 |
| 新人接手 | 读完 440 行 worker 才懂流程 | 看目录名就知道有什么 |

**实施策略**：不一次性大重构。随 v2.2 翻译模块渐进拆分——新建 `services/` 时顺手把 `media.py` `modal_runner.py` 移入；新建 `database/` 时拆 `storage.py`。最后再拆 `api/` 和 `models.py`。

---

## 之前的待推进（已完成或放弃）

| 功能 | 状态 |
|---|---|
| FC2 非标番号适配 | ✅ v1.9 完成 |
| 任务删除 | ✅ v1.9 完成 |
| 海报加载骨架屏 | ✅ v1.9 完成 |
| Cloudflare+DeepSeek 双通道 | ❌ v2.1 尝试后移除（CF 5MB 限制不可行） |

---

## 关键文件

| 文件 | 作用 |
|---|---|
| `app/main.py` | FastAPI 路由 + poster-proxy 代理 |
| `app/config.py` | AppConfig（含 dbo_api_url/key） |
| `app/storage.py` | Job SQLite 存储 |
| `app/worker.py` | Worker 池 / 流水线 |
| `app/media.py` | 媒体发现 + ffmpeg |
| `app/modal_runner.py` | Modal 桥接 |
| `app/static/index.html` | SPA + Dock + PWA（v23） |
| `app/static/app.js` | 导航/画廊/海报/缓存/配置（~550 行）|
| `app/static/styles.css` | 主题/Dock/海报墙/响应式 |
| `docker-compose.yml` | 镜像拉取部署 |
| `Dockerfile` | python:3.10-slim + ffmpeg + git |
| `.env.example` | Modal 密钥模板 |

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/version` | 版本号 |
| GET | `/api/config` | 获取配置 |
| POST | `/api/config` | 保存配置 |
| POST | `/api/jobs` | 创建任务 |
| GET | `/api/jobs` | 列出任务 |
| GET | `/api/jobs/{id}` | 任务详情 |
| POST | `/api/jobs/{id}/cancel` | 取消 |
| POST | `/api/jobs/{id}/retry` | 重试 |
| DELETE | `/api/jobs/{id}` | 删除任务 |
| POST | `/api/jobs/retry-failed` | 批量重试 |
| GET | `/api/dbo-search?q=...&limit=1` | DBO 搜索代理 |
| POST | `/api/test-dbo` | 测试 DBO 连通性 |
| GET | `/api/poster-proxy?url=...` | 海报图片代理 |
| POST | `/api/clear-audio-cache` | 清空音频缓存 |
| GET | `/api/pack?date=ts` | 按日期打包字幕 |

## 外部依赖

- **dbo**：内网 `10.0.0.235:9090` → Web 配置页可填写地址和密钥
- **Modal**：API 密钥通过 docker-compose 环境变量传入
- **JavDB**：通过 dbo 间接访问

## 本地预览

```powershell
cd "C:\Users\jzdxjk\Documents\字幕云翻译"
python -c "import os;os.chdir('.');os.environ['CONFIG_DIR']='.';os.environ['CACHE_DIR']='./cache';os.environ['WATCH_DIR']='.';os.environ['OUTPUT_DIR']='./output';import uvicorn;uvicorn.run('app.main:app',host='0.0.0.0',port=15678)"
```

访问 `http://192.168.100.141:15678`（桌面）或手机同 WiFi 访问。

## 部署

```bash
git clone https://github.com/jzdxjk/subtitle-modal-web.git
# 改 docker-compose.yml 里的密钥和路径
docker-compose up -d
```
