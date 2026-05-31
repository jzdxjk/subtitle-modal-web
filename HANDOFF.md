# HANDOFF - subtitle-modal-web

最后更新: 2026-05-31
当前分支: master

## 一句话现状
项目主链路可用（NAS/Docker Web + Modal 云端识别 + 任务队列 + 海报墙），当前已完成到 v2.4 的 FC2 番号兼容修复；LLM 翻译能力仍处于规划/草案阶段，未在当前代码树完整落地。

## 近期已实现（代码已落地）
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

## 建议下一步（优先级）
1. 在可运行 Python 的环境执行完整测试并记录基线结果
2. 增加 API 集成测试（jobs 生命周期 + dbo/poster 代理）
3. 拆分前端 app.js，优先抽离海报抓取与任务渲染
4. 评估并实现 jobs 分页 API

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
