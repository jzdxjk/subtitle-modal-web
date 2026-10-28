# 字幕助手合并插件 — 交接与当前状态

<!-- SA-HANDOFF-BEGIN SA-20261028-auto-download-01 -->
## 入库自动下载字幕：诊断完成，转入修复（2026-10-28）

### 交接区

- 交接编号：SA-20261028-auto-download-01
- 源任务编号：`01a17ff5-995e-7b13-9e59-9613eab68ded`（本诊断对话）；更早源头 `01a17cd2-2170-7030-b266-5ea30c33b57b`
- 用户确认范围：更新交接文档；在同一项目新建对话修复“入库自动下载字幕”bug、更新插件、本地验证、上传仓库。原话：“更新交接文档,在新对话中 修复bug 更新插件 本地验证 上传仓库”。此前诊断授权原话：“更新交接文档,在新对话中看一下为什么入库自动下载字幕怎么没有生效,比如 wanz-161”。
- 项目目录：主工作树 `E:\E盘codex\字幕云翻译`（分支 `dev`，含大量用户未提交改动，**只读，禁止修改/重置/清理**）；插件实际工作树 `C:\Users\jzdxjk\.codex\worktrees\subtitle-assistant\字幕云翻译`（分支 `codex/subtitle-assistant`，修复只在这里做）。
- 接手任务编号：`01a18036-6765-7c92-a682-90c9139762d6`
- 交接状态：已接手
- 更新时间：2026-10-28 10:01 +08:00

### 任务与版本

- 新阶段目标（用户已确认）：修复 `wanz-161` 暴露的入库自动下载异常 → 更新插件版本并构建 → 本地验证 → 提交并推送仓库。生产部署/重启不在本次授权内，到该边界先停。
- 诊断阶段目标（已完成）：解释为什么 `wanz-161` 新入库后没有自动下载中文字幕。
- 版本位置：工作树分支 `codex/subtitle-assistant`；修复提交 `589a6aa7cdd384e6ab322db88e2808959ec25213`（父提交 `478a2f4`）；`emby-unified-plugin` 版本已升至 `1.0.0.4`（`Version`/`AssemblyVersion`/`FileVersion` 均为 `1.0.0.4`），`Release` 构建 DLL SHA256 `a83591539d97866003f9f4dfcc747d4bd339758a9e77dea8b878940119c74eb1`。工作树未跟踪：`.dotnet/`、`.nuget/`、`docs/SUBTITLE-SOURCES-API.md`（未提交）；已跟踪改动：`docs/HANDOFF-subtitle-assistant.md`（本文件）。

### 诊断结论（只读，已完成）

**根因定性：不是“没触发”，也不是“被条件拒绝”，而是插件在入库 +60 秒执行阶段抛异常，任务中断。**

- 生产 Emby `4.10.2.0`，实际加载 `Emby.SubtitleAssistant, Version=1.0.0.3`；生产 DLL SHA256 `932a3ec4ff0ee5e26f1e2db7673c8f6293d1dc7bd715917aef51f2dd771de309`（与 1.0.0.3 验收同字节）。
- 插件配置 `AutoDownloadOnNewMedia=true`，自动下载开关已开。
- `wanz-161`：内部 Id `66659`，路径 `/strm/影视库/AV/有码/北川杏樹/WANZ-161/WANZ-161-无码破解.strm`，`DateCreated=1793124649` = `2026-10-28 02:10:49 +08:00`。
- 所属库「🖤有码」：类型 `movies`、语言 `zh-CN`、`RequirePerfectSubtitleMatch=false`、跳过已有内嵌字幕=true、最大天数 180；入库时无中文字幕，这些设置都不构成拒绝。
- `2026-10-28 02:11:49.434` 日志：`Warn AutomationEntryPoint: Subtitle completion failed (ArgumentOutOfRangeException)`。时间正好是入库后 60 秒，说明该条目已被 60 秒自动下载队列接收并执行，随后抛 `ArgumentOutOfRangeException`。
- 非个例：`2026-10-27 18:58:10` 到 `2026-10-28 04:44:40` 共 **716 次**同类异常，跨 **15 个** Emby 进程会话。
- 当前存在的 `WANZ-161-无码破解.zh-CN.srt` 是 `2026-10-28 09:37:54` 批量字幕落盘产生，**不是**入库自动下载成功。
- 旁证（独立问题，不在本修复范围）：Strm Assistant 内存超过 1000 MB 时 `3/3` 触发 Emby 重启；近 3 天约 63 次进程启动，会清空 60 秒等待期内存在内存字典里的待处理项。

### 疑似代码位置（待复现验证）

均在 `C:\Users\jzdxjk\.codex\worktrees\subtitle-assistant\字幕云翻译\emby-unified-plugin`：

- `Automation/AutomationEntryPoint.cs` 第 48–59 行 `AfterDelayAsync`（第 57 行为 catch）：`ProcessAsync` 抛出的异常在此 `catch (Exception error) { _logger.Warn("Subtitle completion failed ({0})", error.GetType().Name); }` 被捕获，**只记录异常类型，无堆栈、无条目 ID/路径、无失败阶段**。修复时必须补全。
- `Automation/SubtitleCompletionService.cs` 第 99–101 行 `Skip()`：`item.MediaStreams` 与 `_mediaSources.GetMediaStreams(item.InternalId)`，`InternalId` 越界或流集合访问异常是最可疑的 `ArgumentOutOfRangeException` 来源。
- `Automation/CompletionPolicy.cs` 第 69–76 行 `SkipForStreams`：消费上述流集合做字幕/内嵌/音轨判断。
- `validation/ACCEPTANCE-2026-10-27.md`：1.0.0.3 版本、DLL SHA、五版本验收、生产暂存与 60 秒自动补全基线。

### 决定与限制

- 用户已确认：更新交接文档；新建对话修复 bug、更新插件、本地验证、上传仓库。
- 修复要求：先复现或单测 `Skip()`/`ProcessAsync` 的流访问异常；对 null、空集合、重复流、`InternalId` 访问异常做安全处理；**不得只吞异常**——日志必须包含异常堆栈、条目 Id/路径、失败阶段；新增回归测试。
- 版本与发布：按仓库现有流程提升插件版本（1.0.0.3 → 下一版），`Release` 构建（netstandard2.1），跑本地测试（.NET / Worker / 校验 / 发布工具）并确认 DLL SHA。提交并推送 `codex/subtitle-assistant` 分支；仓库 `jzdxjk/subtitle-modal-web`（已有草稿 PR #1，推送即更新）。
- 授权边界：本次授权到“本地验证 + 上传仓库”为止。生产 Emby 替换 DLL、删旧插件、重启 Emby **未授权**，需另行确认。
- 不可违反：主工作树 `E:\E盘codex\字幕云翻译` 有用户未提交改动，禁止 reset/clean/stash/覆盖；所有代码改动只在隔离工作树。NAS sudo 只能用 `C:\Users\jzdxjk\.codex\nas-sudo.ps1 -Command '<remote command>'`，绝不索取/打印/保存口令。

### 进展与运行状态

- 已完成（2026-10-28）：只读诊断；代码修复；插件版本 `1.0.0.4`；`Release` 构建；本地测试；提交推送。
- 进行中：无。
- 未做：生产 Emby 部署/重启（未授权）；GitHub 正式 release 发布（未授权，需五版本运行验收后由授权操作者执行）。
- 未验证：真实 Emby 运行态下 `GetMediaStreams` 的确切内部抛出点（本机无 Emby 运行时，已用单测覆盖同一调用路径的 `ArgumentOutOfRangeException`）；生产部署。

### 修复结果（2026-10-28 已完成）

- 根因定位：`Skip()` 把 `item.MediaStreams` 与 `_mediaSources.GetMediaStreams(item.InternalId)` 以惰性 `Concat` 交给 `SkipForStreams` 的 `ToArray()` 枚举；`GetMediaStreams(Int64)` 抛出的 `ArgumentOutOfRangeException` 在枚举时冒泡，`AfterDelayAsync` 只记录异常类型，导致入库自动补全中断（`wanz-161`）。
- 代码修改：
  - 新增 `Automation/StreamCollector.cs`：逐源 try/catch 收集流，`InternalId<=0` 不查媒体源，null/空/重复流安全处理，失败经回调上报。
  - `SubtitleCompletionService.Skip()` 改用 `StreamCollector`（媒体源异常不再中断流程）；`ProcessAsync` 用 `SubtitleCompletionException` 标记失败阶段。
  - `AfterDelayAsync` 改为 `ErrorException`，输出异常堆栈 + 条目 Id/路径 + 失败阶段；条目不存在时记 Warn 并跳过。
  - `MissingSubtitleTask` 同步改为按阶段/条目记录。
  - 新增 `emby-unified-plugin.Tests/StreamCollectorTests.cs`（7 个回归测试）。
- 构建与测试：`Release`（`netstandard2.1`）0 警告 0 错误；DLL `1.0.0.4` SHA256 `a83591539d97866003f9f4dfcc747d4bd339758a9e77dea8b878940119c74eb1`；.NET 172 通过（含新增 7）、Worker 24 通过、校验 12（1 跳过）、发布/部署工具 31 通过。
- 提交：`589a6aa`（代码+测试+版本）；本交接文档更新随后提交，一并推送 `origin/codex/subtitle-assistant`（更新 PR #1）。

### 接续动作（已按序完成；生产部署/重启待另行确认）

1. 第一步（只读核对）：核对本交接编号、工作树分支/HEAD、`1.0.0.3` 版本与 SHA、上述代码行；确认主工作树只读边界。不修改业务文件。
2. 第二步（修复）：复现/单测定位 `ArgumentOutOfRangeException`；安全处理 null/空/重复流与 `InternalId` 异常；增强 `AfterDelayAsync` 日志（堆栈 + 条目 Id/路径 + 阶段）；加回归测试。
3. 第三步（更新插件）：按仓库流程升版本、`Release` 构建、确认新 DLL SHA。
4. 第四步（本地验证）：跑 .NET / Worker / 校验 / 发布工具测试并记录结果。
5. 第五步（上传仓库）：提交并推送到 `codex/subtitle-assistant`（更新 PR #1）。**到此停止，生产部署/重启待用户另行确认。**
6. 验收：新增回归测试覆盖原异常路径且通过；构建 0 警告 0 错误；本地测试全绿；推送成功（给出 commit 与远端分支）。

（本交接已接手并完成修复；此前恢复用开场白已停用。）
<!-- SA-HANDOFF-END SA-20261028-auto-download-01 -->

> 以下章节为 2026-10-27 早中期历史记录；其中 `candidate-03`、`1.0.0.0`、SHA256 `2694f299...` 等已被 `1.0.0.3`（SHA256 `932a3ec4...`）取代，仅作历史参考，现状以上面的交接区为准。

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
