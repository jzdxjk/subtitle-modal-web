using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using MediaBrowser.Model.Configuration;
using MediaBrowser.Model.Serialization;

namespace Emby.SubtitleAssistant.Migration;

internal sealed class MigrationException : Exception
{
    public MigrationException(string message) : base(message) { }
}

internal sealed class MigrationLibrary
{
    public string Key { get; }
    public LibraryOptions Options { get; }
    public Action<LibraryOptions> Save { get; }
    public MigrationLibrary(string key, LibraryOptions options, Action<LibraryOptions> save) { Key = key; Options = options; Save = save; }
}

internal static class ProviderKeyMigration
{
    private static readonly IReadOnlyDictionary<string, string> OldNames = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        ["MeiamSub.LocalPool"] = ProviderNames.Local,
        ["ThunderSubtitle"] = ProviderNames.Thunder,
        ["Pool"] = ProviderNames.Pool,
        ["海南鸡字幕"] = ProviderNames.Pool,
        ["海南鸡字幕池"] = ProviderNames.Pool,
        ["ChickenRicePool"] = ProviderNames.Pool,
        ["Emby.ChickenRicePool"] = ProviderNames.Pool
    };
    private const string ExtraThunder = "MeiamSub.Thunder";
    public static string[] ProjectProviderOrder(IEnumerable<string> order)
    {
        var projected = (order ?? Array.Empty<string>()).Select(key =>
        {
            if (key == null || !OldNames.TryGetValue(key, out var name)) return key;
            if (name == ProviderNames.Pool) return ProviderKeys.Pool;
            if (name == ProviderNames.Local) return ProviderKeys.Local;
            if (name == ProviderNames.Thunder) return ProviderKeys.Thunder;
            return key;
        }).ToArray();
        if (ProviderOrder.IsValid(projected)) return projected;
        if (projected.Length == 2 && projected.Contains(ProviderKeys.Local, StringComparer.Ordinal) &&
            projected.Contains(ProviderKeys.Thunder, StringComparer.Ordinal))
            return new[] { ProviderKeys.Pool }.Concat(projected).ToArray();
        return ProviderOrder.Default;
    }
    public static bool HasProviderKeys(LibraryOptions source)
    {
        if (source == null) return false;
        return (source.SubtitleFetcherOrder ?? Array.Empty<string>()).Concat(source.DisabledSubtitleFetchers ?? Array.Empty<string>())
            .Any(key => key != null && (OldNames.ContainsKey(key) || OldNames.Values.Contains(key, StringComparer.Ordinal)));
    }
    public static LibraryOptions Apply(LibraryOptions source, IJsonSerializer json, IReadOnlyDictionary<string, string> explicitNames = null)
    {
        var result = MigrationRunner.Clone(source, json);
        string Resolve(string key) => key != null && explicitNames != null && explicitNames.TryGetValue(key, out var value) ? value : key;
        var oldPresent = new HashSet<string>((source.SubtitleFetcherOrder ?? Array.Empty<string>())
            .Concat(source.DisabledSubtitleFetchers ?? Array.Empty<string>()).Select(Resolve).Where(x => x != null && OldNames.ContainsKey(x)), StringComparer.Ordinal);
        var oldOrderPresent = new HashSet<string>((source.SubtitleFetcherOrder ?? Array.Empty<string>()).Select(Resolve).Where(x => x != null && OldNames.ContainsKey(x)), StringComparer.Ordinal);
        string[] Rewrite(string[] keys, HashSet<string> authoritativeOldKeys)
        {
            if (keys == null) return null;
            var seenSources = new HashSet<string>(StringComparer.Ordinal);
            var rewritten = new List<string>();
            foreach (var key in keys)
            {
                var name = Resolve(key);
                if (name == ExtraThunder) continue;
                if (name != null && OldNames.TryGetValue(name, out var target))
                { if (seenSources.Add(target)) rewritten.Add(target); continue; }
                var previous = OldNames.FirstOrDefault(x => x.Value == name).Key;
                if (previous != null)
                {
                    if (!authoritativeOldKeys.Contains(previous) && seenSources.Add(name)) rewritten.Add(name);
                    continue;
                }
                // Unknown providers remain byte-for-byte keys, including their relative order.
                rewritten.Add(key);
            }
            return rewritten.ToArray();
        }
        result.SubtitleFetcherOrder = Rewrite(source.SubtitleFetcherOrder, oldOrderPresent);
        result.DisabledSubtitleFetchers = Rewrite(source.DisabledSubtitleFetchers, oldPresent);
        return result;
    }
}

internal static class DefaultDisablePolicy
{
    private static readonly string[] Own = { ProviderNames.Pool, ProviderNames.Local, ProviderNames.Thunder };
    // A fresh install disables every managed source. An upgrade also disables restored Pool when no saved choice exists.
    public static LibraryOptions Apply(LibraryOptions source, IJsonSerializer json)
    {
        var result = MigrationRunner.Clone(source, json);
        var disabled = new List<string>(result.DisabledSubtitleFetchers ?? Array.Empty<string>());
        foreach (var name in Own)
            if (!disabled.Any(value => string.Equals(value, name, StringComparison.OrdinalIgnoreCase))) disabled.Add(name);
        result.DisabledSubtitleFetchers = disabled.ToArray();
        return result;
    }
}

internal static class MigrationRunner
{
    internal const int CurrentMigrationVersion = 3;
    internal const string PendingFilename = "subtitle-assistant-migration.pending";
    private static readonly object Gate = new object();
    internal static T Clone<T>(T value, IJsonSerializer json) => json.DeserializeFromString<T>(json.SerializeToString(value));
    public static bool Execute(string configFile, PluginConfiguration current, IJsonSerializer json, IEnumerable<MigrationLibrary> libraries,
        Action<PluginConfiguration> saveConfig, IReadOnlyDictionary<string, string> explicitNames = null)
    {
        lock (Gate)
        {
            try
            {
                configFile = Path.GetFullPath(configFile);
                var configDirectory = Path.GetDirectoryName(configFile);
                var pendingFile = Path.Combine(configDirectory, PendingFilename);
                var alreadyImported = current.MigrationVersion >= 1;
                var migrationComplete = current.MigrationVersion >= CurrentMigrationVersion;
                if (migrationComplete && !File.Exists(pendingFile)) return false;
                var librariesToMigrate = (libraries ?? Array.Empty<MigrationLibrary>()).ToArray();
                var freshInstall = !alreadyImported && !LegacySettingsImporter.HasLegacySettings(configDirectory) &&
                    !librariesToMigrate.Any(library => ProviderKeyMigration.HasProviderKeys(library.Options));
                var imported = alreadyImported ? Clone(current, json) : LegacySettingsImporter.Merge(configDirectory, current, json);
                if (!migrationComplete)
                {
                    imported.ProviderDisplayOrder = ProviderKeyMigration.ProjectProviderOrder(imported.ProviderDisplayOrder);
                    LegacySettingsImporter.NormalizeThunderMaxResults(imported);
                }
                var originalConfig = Clone(current, json);
                var prepared = librariesToMigrate.Select(library => new PreparedLibrary
                {
                    Target = library, Original = Clone(library.Options, json),
                    Migrated = Migrate(library.Options, json, explicitNames, freshInstall)
                }).Where(x => !Same(x.Original.SubtitleFetcherOrder, x.Migrated.SubtitleFetcherOrder)
                    || !Same(x.Original.DisabledSubtitleFetchers, x.Migrated.DisabledSubtitleFetchers)).ToArray();
                var configBytes = File.Exists(configFile) ? File.ReadAllBytes(configFile) : null;
                var backup = Path.Combine(configDirectory, "subtitle-assistant-migration-backups", DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(backup);
                if (configBytes == null) File.WriteAllBytes(Path.Combine(backup, "new-config.missing"), Array.Empty<byte>());
                else File.WriteAllBytes(Path.Combine(backup, "new-config.original"), configBytes);
                for (var i = 0; i < prepared.Length; i++)
                    File.WriteAllText(Path.Combine(backup, "library-" + i + ".json"), json.SerializeToString(new LibraryBackup { Key = prepared[i].Target.Key, Options = prepared[i].Original }), new UTF8Encoding(false));
                File.WriteAllText(pendingFile, "1", new UTF8Encoding(false));
                var attempted = new List<PreparedLibrary>();
                var configAttempted = false;
                try
                {
                    foreach (var library in prepared)
                    {
                        attempted.Add(library); // A failing native save may already have written.
                        library.Target.Save(library.Migrated);
                    }
                    if (!migrationComplete)
                    {
                        imported.MigrationVersion = CurrentMigrationVersion;
                        configAttempted = true;
                        saveConfig(imported); // Settings and completion marker are one final write.
                    }
                    try { File.Delete(pendingFile); } catch { /* A later startup can finish library-only recovery. */ }
                    return true;
                }
                catch
                {
                    var rollbackFailed = false;
                    foreach (var library in attempted.AsEnumerable().Reverse())
                        try { library.Target.Save(library.Original); } catch { rollbackFailed = true; }
                    if (configAttempted)
                    {
                        try { saveConfig(originalConfig); } catch { rollbackFailed = true; }
                        try
                        {
                            if (configBytes != null) File.WriteAllBytes(configFile, configBytes);
                            else if (File.Exists(configFile)) File.Delete(configFile);
                        }
                        catch { rollbackFailed = true; }
                    }
                    if (!rollbackFailed) try { File.Delete(pendingFile); } catch { }
                    throw new MigrationException(rollbackFailed
                        ? "字幕助手迁移未完成，部分回滚失败；服务器迁移备份已保留，未确认迁移成功。"
                        : "字幕助手迁移未完成，已恢复原设置；服务器迁移备份已保留。");
                }
            }
            catch (MigrationException) { throw; }
            catch { throw new MigrationException("字幕助手迁移准备失败，未导入新配置；请检查旧配置格式与服务器文件权限。"); }
        }
    }
    private static LibraryOptions Migrate(LibraryOptions source, IJsonSerializer json, IReadOnlyDictionary<string, string> explicitNames, bool freshInstall)
    {
        var migrated = ProviderKeyMigration.Apply(source, json, explicitNames);
        if (freshInstall) return DefaultDisablePolicy.Apply(migrated, json);
        var hadPoolChoice = (source.SubtitleFetcherOrder ?? Array.Empty<string>())
            .Concat(source.DisabledSubtitleFetchers ?? Array.Empty<string>())
            .Any(key => IsPoolChoice(key, explicitNames));
        if (hadPoolChoice) return migrated;
        var disabled = new List<string>(migrated.DisabledSubtitleFetchers ?? Array.Empty<string>());
        if (!disabled.Contains(ProviderNames.Pool, StringComparer.OrdinalIgnoreCase)) disabled.Add(ProviderNames.Pool);
        migrated.DisabledSubtitleFetchers = disabled.ToArray();
        return migrated;
    }
    private static bool IsPoolChoice(string key, IReadOnlyDictionary<string, string> explicitNames)
    {
        if (key != null && explicitNames != null && explicitNames.TryGetValue(key, out var mapped)) key = mapped;
        return string.Equals(key, ProviderKeys.Pool, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(key, ProviderNames.Pool, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(key, "海南鸡字幕池", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(key, "ChickenRicePool", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(key, "Emby.ChickenRicePool", StringComparison.OrdinalIgnoreCase);
    }
    private static bool Same(string[] left, string[] right) => left == null ? right == null : right != null && left.SequenceEqual(right, StringComparer.Ordinal);
    private sealed class PreparedLibrary { public MigrationLibrary Target; public LibraryOptions Original; public LibraryOptions Migrated; }
    private sealed class LibraryBackup { public string Key { get; set; } public LibraryOptions Options { get; set; } }
}
