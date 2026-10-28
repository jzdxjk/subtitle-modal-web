# 字幕助手更新清单

原生任务 `SubtitleAssistantUpdate` 默认每 24 小时检查正式版。更新通过插件独立网络层执行，安装后只通知 Emby 需要重启，由管理员决定重启时间。

```json
{
  "version": "1.0.0.3",
  "download_url": "https://github.com/jzdxjk/subtitle-modal-web/releases/download/emby-subtitle-assistant-v1.0.0.3/Emby.SubtitleAssistant.dll",
  "sha256": "932a3ec4ff0ee5e26f1e2db7673c8f6293d1dc7bd715917aef51f2dd771de309",
  "plugin_id": "76cd4168-e0b3-4aac-8a52-5cb638121744",
  "channel": "stable",
  "minimum_server_versions": {
    "4.8": "4.8.11.0",
    "4.9": "4.9.1.80",
    "4.10": "4.10.0.40"
  }
}
```

默认清单位于独立的 `emby-subtitle-assistant-update` release 中的 `update.json`。版本必须为四段数字；预发行通道和不兼容宿主不安装。下载包校验 SHA256、程序集名称、程序集版本后才替换固定文件 `Emby.SubtitleAssistant.dll`，不会加载执行候选程序集。

同磁盘 `.subtitle-assistant-update/` 中保留原 DLL 的 `.bak` 备份，临时候选使用 `.bin` 并在退出时清理。已写入磁盘但尚未重启的新版本会阻止重复安装。失败不会用响应正文或带凭据的 URL 写日志。

隔离验收只能在受控测试宿主上通过原生插件配置接口写入临时 `UpdateManifestUrl`，验收结束即恢复；该地址不对设置页开放，生产也不能改成验收地址。
