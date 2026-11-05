using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace Emby.SubtitleAssistant.Updates;

public sealed class UpdateInstallResult
{
    public bool Installed { get; set; }
    public string BackupPath { get; set; }
}

public static class PackageInstaller
{
    private static readonly object Gate = new object();

    internal static UpdateInstallResult Install(byte[] candidate, UpdateManifest manifest, string destination, Version runningVersion,
        CancellationToken ct, Action<string, string, string> replace = null)
    {
        lock (Gate)
        {
            ct.ThrowIfCancellationRequested();
            var targetVersion = manifest?.ValidatePackageMetadata() ?? throw new InvalidDataException("缺少更新清单。");
            destination = Path.GetFullPath(destination);
            if (!string.Equals(Path.GetFileName(destination), "Emby.SubtitleAssistant.dll", StringComparison.Ordinal))
                throw new InvalidDataException("更新目标必须是字幕助手插件文件。");
            var current = ReadIdentity(destination);
            if (current.Name != "Emby.SubtitleAssistant") throw new InvalidDataException("当前插件文件身份不匹配。");
            if (current.Version >= targetVersion || runningVersion >= targetVersion) return new UpdateInstallResult();
            if (candidate == null || candidate.Length == 0) throw new InvalidDataException("更新包为空。");
            using (var hash = SHA256.Create())
            {
                var digest = new StringBuilder(64);
                foreach (var value in hash.ComputeHash(candidate)) digest.Append(value.ToString("x2"));
                if (!string.Equals(digest.ToString(), manifest.sha256, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("更新包 SHA256 校验失败。");
            }
            var staging = Path.Combine(Path.GetDirectoryName(destination), ".subtitle-assistant-update");
            Directory.CreateDirectory(staging);
            var temporary = Path.Combine(staging, "candidate-" + Guid.NewGuid().ToString("N") + ".bin");
            try
            {
                ct.ThrowIfCancellationRequested();
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                { stream.Write(candidate, 0, candidate.Length); stream.Flush(true); }
                var identity = ReadIdentity(temporary);
                if (identity.Name != "Emby.SubtitleAssistant" || identity.Version != targetVersion)
                    throw new InvalidDataException("更新包的程序集名称或版本不匹配。");
                var backup = Path.Combine(staging, "Emby.SubtitleAssistant-" + current.Version + "-" +
                    DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "-" + Guid.NewGuid().ToString("N") + ".bak");
                ct.ThrowIfCancellationRequested();
                (replace ?? File.Replace)(temporary, destination, backup);
                return new UpdateInstallResult { Installed = true, BackupPath = backup };
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
    }

    internal static AssemblyName ReadIdentity(string path)
    {
        try { return AssemblyName.GetAssemblyName(path); }
        catch { throw new InvalidDataException("无法读取插件程序集身份。"); }
    }
}
