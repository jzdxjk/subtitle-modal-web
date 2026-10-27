# 字幕助手运行验收（2026-10-27）

## 最终候选

- 版本：`1.0.0.3`，插件 ID `76cd4168-e0b3-4aac-8a52-5cb638121744`
- 文件：`emby-unified-plugin/bin/Release/netstandard2.1/Emby.SubtitleAssistant.dll`
- SHA256：`932a3ec4ff0ee5e26f1e2db7673c8f6293d1dc7bd715917aef51f2dd771de309`（238592 字节）
- Release 构建 0 警告、0 错误；连续重建字节一致，实测哈希与上表相同
- 本地测试：.NET 165 通过 0 失败；Worker 24 通过；校验 harness 12（1 跳过）；发布/部署工具 31 通过

## 1.0.0.3 修订内容

- 搜索结果大小统一按 1024 进制、一位小数显示为 `X.X KB`（未知 `unknown`），本地/迅雷/海南鸡共用。
- 迅雷时长优先解析真实字幕轴（标签“字幕轴”），否则用接口时长毫秒换算为秒（标签“迅雷API”），都缺时显示 `unknown(迅雷API)`；排序用修正后的秒数。
- 新增全局设置“搜索结果来源顺序”，三行鼠标/触摸拖拽，稳定键 `Pool/Local/Thunder`，默认海南鸡→本地→迅雷；只改来源之间的先后，不改各来源内部排序；保存后需重启 Emby 生效。
- 自动补全仍按各媒体库原生下载器顺序，插件设置不改写媒体库。
- 保存按钮改为与 MagicTools 一致的表单内原生整宽 `emby-button`，去除吸底条与自定义绿色样式。

## 五版本运行验收（1.0.0.3）

同一 DLL 在五个官方 Emby 隔离宿主重跑“插件加载、三下载器、手动搜索下载、结果来源顺序、保存按钮与来源顺序设置”：

| Emby 版本 | 验证容器 | 本机端口 | 报告前缀 | 结果 |
| --- | --- | --- | --- | --- |
| 4.8.11.0 | codex-subtitle-assistant-4811 | 127.0.0.1:19048 | 4811 | 通过 |
| 4.9.1.80 | codex-subtitle-assistant-49180 | 127.0.0.1:19049 | 49180 | 通过 |
| 4.9.5.0 | codex-subtitle-assistant-495 | 127.0.0.1:19059 | 495 | 通过 |
| 4.10.0.40 | codex-subtitle-assistant-410040 | 127.0.0.1:19040 | 410040 | 通过 |
| 4.10.2.0 | codex-subtitle-assistant-4102 | 127.0.0.1:19042 | 4102 | 通过 |

每个版本的四类证据（`reports/` 下）：

- `candidate-09-smoke-<版本>.json`：插件以 `1.0.0.3` 注册一次；五个设置标签；三个原生下载器各一次；两个原生任务；展示上限均 5；管理员设置接口可用；未认证访问被拒绝；服务用户 `0:0`；DLL SHA256 与上图一致。
- `browser-<前缀>-report.json`：13 项全通过（真实管理员登录、五标签切换、默认上限 5、隐藏字段缺席、单标签/跨标签保存、密钥占位、三行来源默认顺序、鼠标拖拽、触摸拖拽、保存后重启提示、原生整宽保存按钮、代理内联结果、移动端无横向溢出）；`browserErrors` 0、`failedResources` 0、`restored` true。
- `candidate-09-manual-abp-192-<版本>.json`：原生手动搜索返回本地字幕、下载保留完整 stem 与原字节、外部 `zh-CN` 字幕流免全库重扫可见。
- `candidate-09-order-<版本>.json`：来源顺序在真实宿主上验证为启动时缓存；保存后需重启 Emby 才改变手动搜索结果先后；重启后配置为迅雷优先时搜索结果以迅雷字幕开头；两来源均存在；自动补全仍按各库原生顺序。

### 来源顺序宿主行为

真实 Emby 4.10.2 证明来源顺序在 Emby 启动时缓存：运行中修改插件来源顺序不会立即改变手动搜索结果，修改媒体库原生下载器顺序也不会覆盖已缓存的插件顺序；保存并在重启后生效。默认配置为 `Pool, Local, Thunder`（海南鸡→本地→迅雷），与旧版表现一致。设置页保存顺序后提示“来源顺序已保存，重启 Emby 后生效。”

## 历史基线（1.0.0.0）

`1.0.0.0`（SHA256 `2694f2991f040f5603d88ab6d250ccf9650e8c7aa3a173bab848726ee981de31`）曾补充验收完整功能路径：代理（HTTP/SOCKS5/认证/bypass/不回退）、权限边界、字幕云提交刷新、60 秒自动补全、原生更新、旧四插件迁移、以及超出界面上限的第六候选。`1.0.0.3` 未改动这些代码路径，只重跑本版受影响与相关的加载/下载/顺序/设置界面。

## 生产暂存

- 生产 Emby 容器未重启（暂存后仍显示 `Up`）；文件已按哈希原子暂存为 `1.0.0.3`。
- 生产插件 `Emby.SubtitleAssistant.dll` 当前 SHA256：`932a3ec4ff0ee5e26f1e2db7673c8f6293d1dc7bd715917aef51f2dd771de309`（与五版本验收使用同一字节）。
- 备份目录：`/volume1/docker/emby/backups/subtitle-assistant-20261027T133659Z-c66a9636`（含上一版 DLL、配置、SQLite 一致性快照 `library.snapshot.db` 及 `stage.json`）。
- 暂存结果：`RetiredDLLs: []`、`RestartRequired: true`、`ProductionRestarted: false`、`LibraryDatabaseSnapshot: true`。
- 运行中的 Emby 进程仍需管理员手动重启后才会加载 `1.0.0.3`。

## 证据位置

- 运行报告：`validation/reports/`（各版本四类报告，见上）
- 浏览器报告截图：`validation/browser-output/`（`browser-output` 不入库，关键报告已复制到 `validation/reports/`）
- NAS 原始任务目录：`/volume1/docker/emby-subtitle-assistant-validation-20261027/`
