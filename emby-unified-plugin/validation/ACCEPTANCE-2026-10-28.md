# 字幕助手运行验收（2026-10-28，v1.0.0.4 / v1.0.0.6 补丁）

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

## v1.0.0.6 补丁验收（新入库回归修复）

本段只覆盖 `1.0.0.5 → 1.0.0.6` 的回归修复与部署核对；设置页、搜索排序、历史补全来源调整等行为沿用
本记录前文 `1.0.0.4` 及 `ACCEPTANCE-2026-10-27.md` 的结论。**没有重新执行五版本容器验收**，仅做单机运行加载核对。

### 问题

生产日志出现真实回归（`wanz-161` 所在新入库路径）：

```text
System.ArgumentOutOfRangeException:
The UTC time represented when the offset is applied must be between year 0 and 10,000.
at System.DateTimeOffset.op_Implicit(DateTime dateTime)
at SubtitleCompletionService.ProcessAsync(...)
```

根因：`BaseItem.DateCreated` 实际为 `DateTimeOffset`。原代码 `item.DateCreated > DateTime.MinValue` 与
`DateTime.UtcNow - item.DateCreated.ToUniversalTime()` 会在 UTC+8 下把 `DateTime.MinValue` 隐式转成
`DateTimeOffset`，偏移换算导致溢出，整个新入库自动补全中断。

### 修复

- 新增 `CompletionPolicy.IsTooOld(LibraryOptions, DateTimeOffset)`，全程使用 `DateTimeOffset` 比较，
  并对 `DateTimeOffset.MinValue` 做显式守卫。
- `SubtitleCompletionService` 的最大入库天数检查改用该函数。
- 新增回归测试 `AutomationTests.MaxAgeCheckHandlesDateTimeOffsetWithoutOverflowing`（覆盖当前时间、
  `DateTimeOffset.MinValue`、31 天前、以及未设置上限四种情况）。
- 版本号提升到 `1.0.0.6`（`Version`/`AssemblyVersion`/`FileVersion`）。

### 产物与哈希

- 文件：`emby-unified-plugin/bin/Release/netstandard2.1/Emby.SubtitleAssistant.dll`
- 归档：`emby-unified-plugin/validation/artifacts/release-1.0.0.6/Emby.SubtitleAssistant.dll`
- 大小：`253952` 字节
- SHA256：`CCA48EDCC1477B969217829C138D1F97C499CB2376155E57C84B5667693DD006`
- 归档件、`bin` 产物与 NAS 线上文件三者哈希一致。DLL 内嵌 `SourceRevisionId=490ef094aefbc88093361c7a29a90a69da06386c`，
  用 `dotnet build -c Release -p:SourceRevisionId=490ef094aefbc88093361c7a29a90a69da06386c` 可逐字节复现该哈希。

### 本地单元测试

- `dotnet test emby-unified-plugin.Tests -c Release`：182 通过、0 失败、0 跳过
  （较 `1.0.0.4` 的 172 项增加 10 项：CompletionScope/新装默认关闭/ProviderSearchCache/DateTimeOffset 回归）。

### 生产部署核对（2026-10-28）

- 1.0.0.5 备份：`/volume1/docker/emby/backups/subtitle-assistant-1.0.0.5-20261028-1345/Emby.SubtitleAssistant.dll`
- 线上文件：`/volume1/docker/emby/config/plugins/Emby.SubtitleAssistant.dll`，SHA256 与上表一致。
- `docker restart emby` 后日志确认：`Loading Emby.SubtitleAssistant, Version=1.0.0.6`。
- `/System/Info/Public` 返回 `Version=4.10.2.0`、服务名 `橘子的Emby`，服务正常。
- 重启后日志 `ArgumentOutOfRangeException` 计数为 0；未触发全库历史补全（避免批量下载）。
