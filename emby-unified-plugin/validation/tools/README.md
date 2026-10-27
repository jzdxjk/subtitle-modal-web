# 冻结 DLL 的更新验收包

在 PowerShell 7 中运行。工具仅通过 `System.Reflection.Metadata` 修改 Assembly 表中的 8 字节版本字段，不执行输入 DLL，不构建主插件；默认版本为 `1.0.0.1`。保留原文件，拒绝原地修改和覆盖已有输出。

从仓库根目录执行：

```powershell
& 'emby-unified-plugin\validation\tools\patch-assembly-version.ps1' `
  -InputPath 'emby-unified-plugin\validation\artifacts\candidate-01\Emby.SubtitleAssistant.dll' `
  -OutputPath 'emby-unified-plugin\validation\artifacts\update-candidate\Emby.SubtitleAssistant.dll'
```

JSON 输出给出输入/输出版本、SHA256 和元数据字段偏移。确认最终冻结版本后，将 InputPath 换成对应冻结产物。该版本补丁只用于隔离更新流程验收，不能作为正式版本发布。

完整 smoke 检查（输出目录应尚未含同名 DLL）：

```powershell
& 'emby-unified-plugin\validation\tools\test-patch-assembly-version.ps1' `
  -InputPath 'emby-unified-plugin\validation\artifacts\candidate-01\Emby.SubtitleAssistant.dll' `
  -OutputDirectory 'emby-unified-plugin\validation\artifacts\update-tool-smoke'
```

smoke 同时检查输入 SHA 未变、输出 AssemblyName.Version、字段外字节全部不变、拒绝原地修改及拒绝覆盖已有输出。
