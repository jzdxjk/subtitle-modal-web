# 字幕助手运行验收（2026-10-28，v1.0.0.4）

本记录只覆盖 `1.0.0.4` 改动的入库自动下载/补全修复。设置页、搜索排序、手动下载等未改动路径沿用
`ACCEPTANCE-2026-10-27.md` 中 `1.0.0.3`（candidate-09）的完整五版本验收结论。

## 最终候选

- 版本：`1.0.0.4`，插件 ID `76cd4168-e0b3-4aac-8a52-5cb638121744`
- 文件：`emby-unified-plugin/bin/Release/netstandard2.1/Emby.SubtitleAssistant.dll`
- SHA256：`a83591539d97866003f9f4dfcc747d4bd339758a9e77dea8b878940119c74eb1`（242176 字节）
- 与 NAS 隔离环境安装的 `candidate-10.dll` 为同一字节。
- 构建说明：DLL 的 `AssemblyInformationalVersion` 内嵌构建时的 `SourceRevisionId`，因此不同提交上直接
  重建会得到不同哈希（源码相同、仅元数据不同）。用
  `dotnet build -c Release -p:SourceRevisionId=478a2f4ba54795187f23ea687b04d674d00f6251`
  可逐字节复现上面的 `a8359153…`。发布时必须使用这一份已验证产物。

## 本次修复（1.0.0.3 → 1.0.0.4）

入库自动补全在 `SubtitleCompletionService.Skip()` 里把 `item.MediaStreams` 与
`_mediaSources.GetMediaStreams(item.InternalId)` 以惰性 `Concat` 交给 `SkipForStreams().ToArray()`
枚举；`GetMediaStreams` 抛出的 `ArgumentOutOfRangeException` 在枚举时才冒泡，而
`AutomationEntryPoint.AfterDelayAsync` 只记录异常类型，导致整条入库自动下载中断（`wanz-161`）。

修复：新增 `Automation/StreamCollector.cs` 逐源 try/catch 收集流并对 `InternalId<=0`、null/空/重复流
安全处理；`Skip()` 改用 `StreamCollector`；`AfterDelayAsync`/`MissingSubtitleTask` 记录异常堆栈、
条目 Id/路径与失败阶段。新增 `emby-unified-plugin.Tests/StreamCollectorTests.cs`（7 个回归测试）。

## 五版本运行验收（1.0.0.4）

同一 DLL 在五个官方 Emby 隔离宿主上重跑“插件加载”与“补全管线”，每个版本的三类结果均通过：

| Emby 版本 | 验证容器 | smoke 加载 | completion 新增入库 | completion 补全任务 |
| --- | --- | --- | --- | --- |
| 4.8.11.0 | codex-subtitle-assistant-4811 | 通过 | 通过（61.2s） | 通过 |
| 4.9.1.80 | codex-subtitle-assistant-49180 | 通过 | 通过（61.0s） | 通过 |
| 4.9.5.0 | codex-subtitle-assistant-495 | 通过 | 通过（61.9s） | 通过 |
| 4.10.0.40 | codex-subtitle-assistant-410040 | 通过 | 通过（62.3s） | 通过 |
| 4.10.2.0 | codex-subtitle-assistant-4102 | 通过 | 通过（60.7s） | 通过 |

每类证据（`reports/` 下）：

- `candidate-10-smoke-<版本>.json`：插件以 `1.0.0.4` 注册一次；五个设置标签；三个原生下载器各一次；
  两个原生任务；管理员设置接口可用；未认证访问被拒绝；服务用户 `0:0`；DLL SHA256 与上表一致。
- `candidate-10-completion-new-<版本>.json`：`AutoDownloadOnNewMedia` 入库约 60 秒后落盘中文字幕，
  完整 stem 保留、原始字节一致、外部 `zh`/`zh-CN` 字幕流可见（`SixtySecondDelayObserved=true`）。
- `candidate-10-completion-backfill-<版本>.json`：`SubtitleAssistantMissingSubtitles` 原生任务
  `Completed`，补全下载成功，已存在中文字幕时跳过下载。

补充：`candidate-10-manual-abp-192-4.10.2.0.json` 原生手动本地下载在 4.10.2 抽查通过（未改动路径）。

## 本地单元测试

- `dotnet test emby-unified-plugin.Tests -c Release`：172 通过、0 失败、0 跳过（含新增
  `StreamCollectorTests` 7 项，覆盖 `GetMediaStreams` 抛 `ArgumentOutOfRangeException` 的同一调用路径）。

## 关于旧 automation 探针

`candidate-10-automation-*-4.10.2.0.json` 显示 `Passed:false`，这不是 1.0.0.4 回归：旧的
`automation_probe` 依赖被替换的池地址，而池地址现已固定在代码里，探针无法命中自有 fixture。
已知良好的 `1.0.0.3`（`candidate-09-automation-new-4.10.2.0.json`）同样失败且 `PoolDownloadRequests=0`。
该探针已被 `completion_probe.py`（本地字幕 fixture，直接驱动 `Skip()`/`StreamCollector`）取代。

## 生产与更新状态

- 生产 `emby` 容器未改动、未重启，仍运行 `1.0.0.3`（SHA256
  `932a3ec4ff0ee5e26f1e2db7673c8f6293d1dc7bd715917aef51f2dd771de309`）。
- “字幕助手：检查并安装更新”计划任务当前无法升到 `1.0.0.4`：指针发布
  `emby-subtitle-assistant-update` 的 `update.json` 仍指向 `1.0.0.3`，没有
  `emby-subtitle-assistant-v1.0.0.4` 正式发布，任务判定“无更新版本”后正常退出（非代理/权限故障）。

## 证据位置

- 运行报告：`emby-unified-plugin/validation/reports/candidate-10-*.json`（本目录，18 份）
- NAS 原始目录：`/volume1/docker/emby-subtitle-assistant-validation-20261027/`（reports、incoming/candidate-10.dll）
