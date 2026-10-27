# 字幕助手运行验收（2026-10-27）

## 最终候选

- 版本：`1.0.0.1`，插件 ID `76cd4168-e0b3-4aac-8a52-5cb638121744`
- 文件：`emby-unified-plugin/bin/Release/netstandard2.1/Emby.SubtitleAssistant.dll`
- SHA256：`71b23a58a9f633d9bbd6e26dd8cfec1e150fd6aaeb0721cc5bbef1abe514ad45`
- Release 构建 0 警告、0 错误；连续两次重建字节一致
- 单元与接口测试：153 通过，0 失败

## 1.0.0.1 设置页修订验收

最终二进制已在隔离宿主 `codex-subtitle-assistant-4102`（官方 Emby `4.10.2.0`，`127.0.0.1:19042`）完成运行与真实浏览器验收。

- `plugin_smoke.py`（报告 `reports/candidate-05-smoke-4.10.2.0.json`）：插件以 `1.0.0.1` 注册一次；五个设置标签；三个原生下载器各注册一次；两个原生任务存在；展示上限均为 5；管理员设置接口可用；未认证访问被拒绝。
- `browser_settings_probe.cjs`（报告 `reports/browser-4102-report.json`）：9 项全部通过，浏览器错误 0，失败资源 0，设置已恢复。
- 九项覆盖：管理员设置快照、真实登录、五标签切换、三个默认上限为 5、固定语言标记/更新清单/自定义测试地址不再出现、单标签与跨标签保存互不污染、Token 与代理密码重载后留空但保留存在占位、更新按钮发现并调用原生任务（截获，不实际执行）、代理测试在按钮旁内联显示路由与延迟。
- 截图：`browser-output/4102-{local,thunder,pool,cloud,proxy}.png`

本版设置页实现：居中的胶囊标签栏；新入库自动补全移入“全局设置”；中文字幕语言标记固定为 `zh-CN` / `zh-TW`；更新清单地址固定在代码中、设置页不再提供入口；代理测试按用途自动选择目标，并在按钮旁直接显示代理/直连与实际延迟。

## 五版本运行基线（1.0.0.0）

`1.0.0.0`（SHA256 `2694f2991f040f5603d88ab6d250ccf9650e8c7aa3a173bab848726ee981de31`）已在五个真实官方 Emby 隔离宿主全部通过运行验收：

| Emby 版本 | 验证容器 | 本机端口 |
| --- | --- | --- |
| 4.8.11.0 | codex-subtitle-assistant-4811 | 127.0.0.1:19048 |
| 4.9.1.80 | codex-subtitle-assistant-49180 | 127.0.0.1:19049 |
| 4.9.5.0 | codex-subtitle-assistant-495 | 127.0.0.1:19059 |
| 4.10.0.40 | codex-subtitle-assistant-410040 | 127.0.0.1:19040 |
| 4.10.2.0 | codex-subtitle-assistant-4102 | 127.0.0.1:19042 |

基线覆盖插件加载、三源搜索与下载、HTTP/SOCKS5 代理、权限边界、字幕云提交与刷新、60 秒自动补全、原生更新、旧四插件迁移和真实浏览器设置页。

`1.0.0.1` 相对 `1.0.0.0` 仅改动设置页呈现、隐藏固定字段、代理测试返回路由与延迟，以及把中文字幕取值收敛到同一组常量（值仍为 `zh-CN` / `zh-TW`）。搜索、下载、代理网络层、字幕云、自动补全和更新安装代码路径未改，因此本次不重跑五版本全矩阵；残余风险是 4.8/4.9 的浏览器 CSS 未随新样式复测。

## 生产暂存

- 生产 Emby 容器未重启；文件已按哈希原子暂存为 `1.0.0.1`。
- 生产插件 `Emby.SubtitleAssistant.dll` 当前 SHA256：`71b23a58a9f633d9bbd6e26dd8cfec1e150fd6aaeb0721cc5bbef1abe514ad45`
- 备份目录：`/volume1/docker/emby/backups/subtitle-assistant-20261027T090540Z-f22a5508`（含上一版 DLL、配置与 SQLite 一致性快照）
- 暂存结果：`RestartRequired: true`，`ProductionRestarted: false`
- 运行中的 Emby 进程仍需管理员手动重启后才会加载 `1.0.0.1`。

## 证据位置

- 运行报告：`validation/reports/`
- 浏览器报告与截图：`validation/browser-output/`（`browser-output` 不入库，关键报告已复制到 `validation/reports/`）
- NAS 原始任务目录：`/volume1/docker/emby-subtitle-assistant-validation-20261027/`
