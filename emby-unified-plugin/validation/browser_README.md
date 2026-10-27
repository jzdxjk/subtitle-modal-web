# 真实浏览器设置页验收

`browser_settings_probe.cjs` 使用官方 Playwright Docker 镜像与同版本 npm 包（固定 `1.62.1`）。镜像包含浏览器和系统依赖，npm 包单独安装，版本必须匹配；参见 [Playwright Docker 文档](https://playwright.dev/docs/docker)。

浏览器仅运行在本任务的 `codex-subtitle-assistant-browser` 容器：1 CPU、1 GiB、host 网络，无发布端口、无生产目录或 Docker socket 挂载。只挂任务私有 browser 工作目录及对应隔离 Emby 的只读 `session.json`，完成后用 `--rm` 清理容器，保留镜像。

每次必须先从 runtime 代理取得该 host 的配置锁，完成后交还；浏览器不启动、重启或停止 Emby。脚本只接受五个授权 loopback 端口：

| Emby | 端口 | 报告与截图前缀 |
| --- | --- | --- |
| 4.8.11.0 | 19048 | 4811 |
| 4.9.1.80 | 19049 | 49180 |
| 4.9.5.0 | 19059 | 495 |
| 4.10.0.40 | 19040 | 410040 |
| 4.10.2.0 | 19042 | 4102 |

验证原生管理员登录、五标签切换、三个初始展示数为 5、单标签及跨标签保存、Token/密码仅显示存在占位、页面重载不回显、保存按钮为原生整宽按钮且无吸底条、三行来源顺序控件的鼠标与触摸拖拽、顺序保存后的重启提示，以及桌面和移动视口的宽度与横向溢出。顺序保存只验证配置持久化与提示；Emby 启动时缓存来源顺序，重启后的真实搜索顺序由 `order_probe.py` 单独验证。

随机测试密钥和原有设置只保留在进程内，`finally` 恢复并核对原设置及原密钥。不开 trace、video、storageState；截图遮挡密钥和代理用户名。通过后才把不含凭据的 `browser-output/<前缀>-report.json` 与五张设置页 PNG 取回项目。`report.json` 是最后一轮的便利副本；各版本结果以带前缀的报告为准。
