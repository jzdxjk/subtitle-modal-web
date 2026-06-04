# HANDOFF - subtitle-modal-web

最后更新: 2026-06-05
当前分支: master

## 一句话现状
项目主链路可用（NAS/Docker Web + Modal 云端识别 + 任务队列 + 海报墙），v2.7 彻底修复并发任务字幕文件互删问题（快照范围限定 + produced 过滤 + 不删 leftover）；LLM 翻译能力仍处于规划/草案阶段，未在当前代码树完整落地。

## 近期已实现（代码已落地）
- v2.7 并发任务字幕文件互删修复（纵深防御）
  - **根因修复**: `_snapshot` 扫描整个共享 `/output/` 目录，并发任务的 before/after 快照差集会包含其他任务写入的文件，导致 `_normalize_outputs` 误删或覆盖
    - `_snapshot` 新增 `expected` 参数，只监控当前任务的目标文件，从源头切断其他任务文件的混入
    - `launch()` → `ModalRunHandle` → `wait()` 全链路传递 `expected`
    - 关键文件: app/modal_runner.py
  - **第二层防御**: `_normalize_outputs` 入口过滤 produced 列表，用哈希后缀剥离 + stem 匹配排除不属于当前任务的文件
    - 关键文件: app/worker.py
  - **移除危险逻辑**: 删除 leftover 文件 `unlink()` 清理，避免误删其他任务文件
  - **审计确认**: 全量扫描所有文件删除/覆盖路径，确认除 `_normalize_outputs` 外无其他风险点
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

## 已知风险与技术债
- 文档与代码可能存在时间差
  - 历史 handoff 曾包含计划性内容，接手时请以代码树和 git log 为准
- 前端 app.js 体量较大，状态与视图逻辑耦合
  - 建议后续拆分 api/jobs/poster/ui 模块
- API /api/jobs 目前默认最多返回 100 条
  - 长期运行下历史可见性有限，建议补分页
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
4. 评估并实现 jobs 分页 API
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
