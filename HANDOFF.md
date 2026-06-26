# HANDOFF - subtitle-modal-web

最后更新: 2026-06-12
当前分支: master

## 一句话现状
项目主链路可用（NAS/Docker Web + Modal 云端识别 + 任务队列 + 海报墙），v2.9 新增 watchdog 小文件忽略索引，避免同一小文件目录被每轮重复扫描；LLM 翻译能力仍处于规划/草案阶段，未在当前代码树完整落地。

## 近期已实现（代码已落地）
- v2.9 watchdog 小文件重复扫描抑制
  - **小文件忽略索引**: 为 watchdog 增加跨重启持久化的 `watchdog_ignored_small_files.json`
    - 对已判定为“小于阈值”的监控入口直接跳过后续扫描
    - 关键文件: app/worker.py
  - **自动失效重判**: 当文件大小、mtime、文件集合发生变化时，忽略记录自动失效并重新扫描
    - 关键文件: app/worker.py
  - **媒体辅助函数**: 新增 `list_small_av_files()`，专门识别“有 AV 号但低于阈值”的文件
    - 关键文件: app/media.py
  - **测试覆盖**: 新增 ignore store 持久化、失效条件、重新放行等测试
    - 关键文件: tests/test_core.py
  - **PWA 缓存版本**: Service Worker 缓存名从 `subtitle-web-v3` 升至 `v4`
    - 关键文件: app/static/sw.js
  - **缓存参数**: `index.html` 中 `app.js` 和 `styles.css` 的 `?v=` 参数从 72 升至 73
    - 关键文件: app/static/index.html
  - **Docker 镜像**: 计划发布 `jzdxjk/subtitle-modal-web:v2.9`
  - 版本号: v2.8 → v2.9

- 2026-06-08 仓库与文档整理
  - **GitHub 默认分支修复**: 远程仓库 `jzdxjk/subtitle-modal-web` 原先同时存在 `main` 与 `master`，GitHub 首页显示的是内容过少的 `main`，导致 README 看起来像“消失”
    - 已将 `master` 中的完整内容同步到 `main`
    - 已将 GitHub 默认分支切换到 `main`
    - 已删除远程 `master`，避免后续再次出现首页内容与实际工作分支不一致
  - **README 状态核验**: 已确认远程与本地 `subtitle-modal-web/README.md` 均为正常 UTF-8，PowerShell 里出现的中文乱码仅为终端显示问题，不是文件损坏
  - **本地仓库结构整理**:
    - 原先 `subtitle-modal-web` 位于 `字幕云翻译` 目录内部，且一度不是独立 Git 仓库，容易与父项目 git 状态混淆
    - 现已将其整理为独立仓库并移动到同级目录:
      - `C:\Users\jzdxjk\Documents\字幕云翻译`
      - `C:\Users\jzdxjk\Documents\subtitle-modal-web`
    - 当前两个项目已彻底解耦，后续应分别进入各自目录执行 `git status` / `commit` / `push`

- v2.8 画廊分页导航 + 性能优化 + 打包数量修复
  - **画廊分页导航**: 底部页码按钮（«‹ 1 2 ›»），每页 10 个有海报的日期，点击可跳转
    - `galleryPageIndex` 替代 `galleryDaysPage`，支持首页/末页/上一页/下一页
    - 关键文件: app/static/app.js, app/static/styles.css
  - **PWA 缓存版本**: Service Worker 缓存名从 `subtitle-web-v2` 升至 `v3`，确保 PWA 加载新资源
    - 关键文件: app/static/sw.js
  - **缓存参数**: `index.html` 中 `app.js` 和 `styles.css` 的 `?v=` 参数从 71 升至 72
    - 关键文件: app/static/index.html
  - **轻量哈希优化**: 轮询哈希从 `JSON.stringify` 全量序列化改为 status 聚合统计 + progress 总和
    - 解决了只看 `jobs[0]` 导致非首任务状态变化漏检的 bug
    - 性能: O(n) 遍历远快于 JSON.stringify，1000 条任务约 0.1ms
    - 关键文件: app/static/app.js
  - **已完成数量减少修复**: `list_jobs()` 去掉默认 LIMIT 100，返回全部任务
    - 关键文件: app/storage.py
  - **打包数量与画廊不一致修复**: 后端 `get_by_completion_date` 加 `json_array_length(output_files) > 0` 过滤空 output_files 的任务
    - 关键文件: app/storage.py
  - **打包按钮显示文件数**: 从显示任务数改为显示文件总数（`output_files` 累加）
    - 关键文件: app/static/app.js
  - 版本号: v2.7 → v2.8

- v2.7 并发任务字幕文件互删修复（AV 番号方案）
  - **v2.7 初版问题**: `_snapshot` 改为只监控 `expected` 路径（scoped snapshot），但 Modal 产出的文件是脏名（如 `hhd800.com@ROYD-317-30aa362f4530.srt`），不在 expected 中 → `produced` 为空 → 画廊无海报 + 输出文件名未规范化
  - **根因修复**: 还原 `_snapshot` 为目录扫描（能发现脏名文件），改用 `extract_av_code` 做 AV 番号匹配过滤
    - `_snapshot` 移除 `expected` 参数，恢复 `rglob` 目录扫描
    - `ModalRunHandle` 移除 `_expected` 字段，`launch()` 移除 `expected` 参数
    - 关键文件: app/modal_runner.py
  - **过滤逻辑修复**: `_normalize_outputs` 从 stem 匹配（`hhd800.com@ROYD-317` ≠ `ROYD-317`）改为 AV 番号匹配（`extract_av_code` 正确提取 `ROYD-317`）
    - 并发安全：任务A（ROYD-317）不会误处理任务B（ADVO-233）的文件
    - leftover 清理恢复 `unlink()`，经 AV 番号过滤后只删除属于当前任务的多余文件
    - 移除未使用的 `import re`
    - 关键文件: app/worker.py
  - **Docker 镜像**: `jzdxjk/subtitle-modal-web:v2.7` 已推送 Docker Hub
  - 版本号: v2.6 → v2.7

- v2.6 跨任务文件误删修复 + 画廊闪烁修复 + Modal 竞态修复
  - **根因修复**: `_snapshot` 用简单集合差集检测新文件，导致之前任务遗留的 `.srt` 被误判为当前产出，随后被 `_normalize_outputs` 清理删除
    - 改为 `{path: mtime}` 字典，只检测**新创建或被修改**的文件
    - 关键文件: app/modal_runner.py
  - **画廊闪烁修复**: 每 5 秒轮询即使数据无变化也用 `innerHTML` 重建整个画廊 DOM
    - `loadJobs` 分离 tabHash / galleryHash，运行中任务进度变化不触发画廊重渲染
    - `renderHome()` 在写入 `innerHTML` 前 normalize 比较新旧 HTML（忽略海报 src），相同则跳过
    - 关键文件: app/static/app.js
  - **Modal 竞态修复**: `_ensure_repo` 每次 launch 都 git fetch，修改 `.git/FETCH_HEAD` 导致 Modal 构建失败
    - git fetch 结果缓存 1 小时
    - 关键文件: app/modal_runner.py
  - **调试日志**: worker.py 添加 `[normalize]`/`[skip]`/`[verify]` 日志，方便排查文件丢失
    - 关键文件: app/worker.py
  - 版本号: v2.5 → v2.6

- v2.5 字幕文件丢失修复 + P0 bug 修复
  - 修复 `_normalize_outputs` 返回已删除路径的问题（从源头消除 `(missing)` 根因）
  - 任务完成时验证文件存在性，确保数据库只记录真实文件
  - 源文件夹移动时保护输出文件，防止连带删除已生成的字幕
  - 修复 ffmpeg 进度解析 bug（`_parse_ffmpeg_time` 除数 /10 → /100）
  - 前端 XSS 漏洞修复（添加 `escapeHtml()` 转义所有动态数据）
  - 新增 3 个单元测试覆盖边界情况
  - 关键文件:
    - app/worker.py
    - app/media.py
    - app/static/app.js
    - tests/test_core.py

- v2.4 FC2 番号修复
  - 支持并统一映射以下格式用于 DBO 搜索:
    - FC2PPV-4907804 -> fc2-4907804
    - FC2-PPV-4907804 -> fc2-4907804
    - FC2-4907804 -> fc2-4907804
  - 关键文件:
    - app/media.py
    - app/static/app.js

- 任务系统
  - 任务创建、查询、取消、重试、批量重试、删除
  - 队列状态: queued/running/cancelling/cancelled/failed/done
  - 关键文件:
    - app/main.py
    - app/storage.py
    - app/worker.py

- 执行链路
  - ffmpeg 本地抽音频 -> Modal 云端推理 -> 字幕归档输出
  - 带阶段进度展示与失败信息回写
  - 关键文件:
    - app/media.py
    - app/modal_runner.py
    - app/worker.py

- 前端与展示
  - SPA 四视图（主页/队列/提交/配置）
  - 主页海报墙（按完成日期分组）
  - DBO 搜索代理 + poster-proxy 图片代理
  - 关键文件:
    - app/static/index.html
    - app/static/app.js
    - app/static/styles.css

## 当前未完成/计划中（请勿视为已上线）
- LLM 翻译模块（ASR 后自动翻译 .zh.srt）
  - 当前仓库未见完整落地文件（例如 app/services/translator.py）
  - 若继续推进，请按“可开关、可回退、失败不阻断主链路”原则实施
- 本地 Docker Desktop 文件大小过滤验证
  - 已确认本机 Docker / Docker Compose 可用，但直接执行 `docker compose up -d --build` 时会与现有容器名冲突
  - 冲突容器为 `subtitle-modal-web`
    - 来自当前仓库 `C:\Users\jzdxjk\Documents\字幕云翻译\docker-compose.yml`
    - 当前正在运行，端口映射为 `http://localhost:9198`
    - `docker inspect` 显示其挂载并非本地 `./media -> /mnt/media`
      - 实际 `WATCH_DIR=/mnt/115/中字制作区`
      - `/output` 挂到外部字幕包目录
      - `/cache` 指向 `C:\Users\jzdxjk\Documents\字幕云翻译\subtitle-modal-web`
      - `/config` 指向 `C:\Users\jzdxjk\Documents\字幕云翻译\config`
  - 因 `docker-compose.yml` 写死了 `container_name: subtitle-modal-web`，无法直接再起第二个 compose 项目
  - 下一步建议：
    - 不要停掉现有容器
    - 在新对话中走“临时第二实例”方案：去掉/覆盖 `container_name`，改独立端口与独立本地挂载，把 `WATCH_DIR` 指向本地测试目录，再做大/小文件模拟验证
  - 本次已完成的排查证据：
    - `docker --version` / `docker compose version` 正常
    - `docker compose -p subtitle-web-local up -d` 失败原因为 container name conflict，而非镜像缺失
    - 本机已存在可复用镜像 `subtitle-modal-web:latest`
  - 2026-06-12 已补充临时第二实例落地文件：
    - `docker-compose.temp-second-instance.yml`
    - `.env.temp-second-instance.example`
    - README 增加独立启动说明
  - 当前约定：
    - 主实例 compose 保持不动
    - 临时实例宿主机端口使用 `9199`
    - 临时实例独立挂载 `./temp-second-instance/{media,output,cache,config}`

## 已知风险与技术债
- 文档与代码可能存在时间差
  - 历史 handoff 曾包含计划性内容，接手时请以代码树和 git log 为准
- 前端 app.js 体量较大，状态与视图逻辑耦合
  - 建议后续拆分 api/jobs/poster/ui 模块
- API /api/jobs 无分页，全量返回
  - 任务量上千后每 5 秒轮询的响应体积和前端 JSON 解析开销会线性增长
  - 建议后续加 `?limit=&offset=` 分页 + 增量查询
- PWA Service Worker 缓存策略
  - HTML/CSS/JS 使用 network-first，但 `sw.js` 中预缓存列表需手动更新
  - **每次修改静态资源后必须递增 `sw.js` 的 `CACHE` 版本名**，否则 PWA 会继续使用旧缓存
  - 同时更新 `index.html` 中的 `?v=` 缓存参数
- API 无认证（所有端点可匿名访问）
  - 如暴露到公网需增加鉴权
- Docker 以 root 运行
  - 建议 Dockerfile 添加非 root 用户
- docker-compose 端口 0.0.0.0:8898 暴露全网
  - 如仅内网使用建议改为 127.0.0.1:8898

## 建议下一步（优先级）
1. Dockerfile 添加非 root 用户（安全基线）
2. 增加 API 集成测试（jobs 生命周期 + dbo/poster 代理）
3. 拆分前端 app.js，优先抽离海报抓取与任务渲染
4. 为 /api/jobs 加分页 + 增量查询（任务量增长后的性能保障）
5. API 增加基础认证（如暴露到公网）

## 备选方案记录（暂不实施）
- 目标：在不改变现有主方案的前提下，为“手动提交任务”增加提取来源开关。
- 方案：
  - 前端提交区增加开关：
    - 挂载文件系统（默认）
    - STRM/115 直链提取
  - 后端仅对手动任务按开关分流：
    - 挂载模式：保持当前 `Path.exists()` 与本地扫描逻辑
    - 直链模式：允许 `http(s)` 输入，`ffmpeg -i <url>` 直接抽音频
  - 监控目录自动任务（watchdog）保持现状，不走直链模式
- 原因：
  - 不破坏当前自动翻译稳定性
  - 直链可能过期/限速/需要额外鉴权，适合手动按需启用
- 安全建议：
  - 直链模式增加域名或主机白名单（如仅允许内网 115 服务地址）

## 本地运行（示例）
- Docker:
  - docker compose up -d --build
- Web:
  - http://NAS_IP:8898

## 关键路径速查
- 后端入口: app/main.py
- 任务执行: app/worker.py
- 媒体处理: app/media.py
- Modal 桥接: app/modal_runner.py
- 任务存储: app/storage.py
- 前端主逻辑: app/static/app.js
