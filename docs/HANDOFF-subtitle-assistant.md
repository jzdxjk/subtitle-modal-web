# 字幕助手合并插件 — 交接与当前状态

## 目标

将本地字幕、迅雷字幕、海南鸡字幕、字幕云合并为一个 Emby 插件：五个设置标签、三个原生下载器、共享番号/搜索/排序规则、全局 HTTP/SOCKS5 代理、原生更新任务。硬性兼容目标：同一 `Emby.SubtitleAssistant.dll` 运行于 Emby 4.8.11.0 / 4.9.1.80 / 4.9.5.0 / 4.10.0.40 / 4.10.2.0。

## 工作区与分支

- 隔离工作树：`C:\Users\jzdxjk\.codex\worktrees\subtitle-assistant\字幕云翻译`
- 分支：`codex/subtitle-assistant`
- 原工作树 `E:\E盘codex\字幕云翻译` 有未提交改动，**不要重置或覆盖**。
- 计划：`docs/superpowers/plans/2026-10-27-subtitle-assistant-implementation.md`
- 验收记录：`emby-unified-plugin/validation/ACCEPTANCE-2026-10-27.md`

## 已完成

- 插件、共享解析/排序/缓存、三个原生提供器、海南鸡接口兼容、字幕云桥接、五标签 Web、权限、代理、迁移、自动补全、原生更新任务。
- 本地测试：.NET 152、Worker/Node 24、Python 校验 12（1 跳过）、发布/部署工具 31，全部通过。
- Release 构建与候选 `candidate-03` 字节一致，SHA256 `2694f2991f040f5603d88ab6d250ccf9650e8c7aa3a173bab848726ee981de31`。
- 五版本真实 Emby 隔离宿主运行矩阵全部通过（见验收记录与 `validation/reports`、`validation/browser-output`）。

## 尚未完成

1. **用户手动重启 Emby**：生产已暂存新 DLL 并移出五个旧 DLL，重启后才加载并触发旧配置迁移。
2. 重启后核对：插件加载、五标签、三下载器、旧配置迁移结果、代理与更新任务。
3. 验证证据归档后停止自有 4.10.2 验证容器与 NAS 校验 mock 服务；**绝不停止生产 `emby` 容器**。

## 已完成（2026-10-27）

- Git 提交 `befc5bc`，分支 `codex/subtitle-assistant` 已推送。
- GitHub 版本 release `emby-subtitle-assistant-v1.0.0.0` 与指针 release `emby-subtitle-assistant-update` 已发布并通过校验。
- 草稿 PR：https://github.com/jzdxjk/subtitle-modal-web/pull/1
- 池端 Worker `chickenrice-subtitle-pool` 已部署（Version `2cb5022d-c723-49e3-9803-af7264046fdb`，线上健康与新查询已验证）。
- NAS 生产暂存完成，备份 `/volume1/docker/emby/backups/subtitle-assistant-20261027T080421Z-ba21a7a8`；生产容器未重启。

## 不可违反的边界

- NAS sudo 只能用 `C:\Users\jzdxjk\.codex\nas-sudo.ps1 -Command '<remote command>'`，绝不索取/打印/保存口令。
- 生产 Emby 未安装新 DLL、未删旧插件、未重启；所有改动先在隔离环境完成。
- 自动更新只消费带 `emby-subtitle-assistant-v...` tag 的正式发布。
