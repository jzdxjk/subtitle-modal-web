using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using Emby.SubtitleAssistant.Migration;
using MediaBrowser.Model.Configuration;
using MediaBrowser.Model.Serialization;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class MigrationTests
{
    [Fact]
    public void VersionOneUpgradeRemovesOnlyPoolAndProjectsOrdersWithoutResettingUserConfiguration()
    {
        using var files = new Fixture();
        var current = new PluginConfiguration
        {
            MigrationVersion = 1, ThunderMaxResults = 5, LocalPaths = "/kept",
            ProviderDisplayOrder = new[] { "Pool", "Thunder", "Local" }
        };
        var options = new LibraryOptions
        {
            SubtitleFetcherOrder = new[] { "Other A", "海南鸡字幕池", ProviderNames.Thunder, ProviderNames.Local, "Other B" },
            DisabledSubtitleFetchers = new[] { "Pool", ProviderNames.Local, "Other disabled" },
            PreferredMetadataLanguage = "fr", SubtitleDownloadLanguages = new[] { "zh-CN" }, SaveSubtitlesWithMedia = false
        };
        var library = new MigrationLibrary("library-a", options, value => options = value);
        PluginConfiguration saved = null;

        Assert.True(MigrationRunner.Execute(files.ConfigPath, current, Json(), new[] { library }, value => saved = value));

        Assert.Equal(2, saved.MigrationVersion);
        Assert.Equal(10, saved.ThunderMaxResults);
        Assert.Equal("/kept", saved.LocalPaths);
        Assert.Equal(new[] { "Thunder", "Local" }, saved.ProviderDisplayOrder);
        Assert.Equal(new[] { "Other A", ProviderNames.Thunder, ProviderNames.Local, "Other B" }, options.SubtitleFetcherOrder);
        Assert.Equal(new[] { ProviderNames.Local, "Other disabled" }, options.DisabledSubtitleFetchers);
        Assert.Equal("fr", options.PreferredMetadataLanguage);
        Assert.Equal(new[] { "zh-CN" }, options.SubtitleDownloadLanguages);
        Assert.False(options.SaveSubtitlesWithMedia);
    }

    [Fact]
    public void VersionOneUpgradeClampsLegacyThunderLimitAboveNewMaximum()
    {
        using var files = new Fixture();
        var current = new PluginConfiguration { MigrationVersion = 1, ThunderMaxResults = 25 };
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "Pool", ProviderNames.Local, ProviderNames.Thunder } };
        var library = new MigrationLibrary("library-a", options, value => options = value);
        PluginConfiguration saved = null;

        Assert.True(MigrationRunner.Execute(files.ConfigPath, current, Json(), new[] { library }, value =>
        {
            value.Validate();
            saved = value;
        }));

        Assert.Equal(10, saved.ThunderMaxResults);
        Assert.Equal(new[] { ProviderNames.Local, ProviderNames.Thunder }, options.SubtitleFetcherOrder);
    }

    [Fact]
    public void VersionZeroImportClampsLegacyThunderLimitBeforeConfigurationValidation()
    {
        using var files = new Fixture();
        files.Write("ThunderSubtitle.json", "{\"EnableAutoDownloadOnNewMedia\":false}");
        var current = new PluginConfiguration { ThunderMaxResults = 25 };
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "Pool", ProviderNames.Local, ProviderNames.Thunder } };
        var library = new MigrationLibrary("library-a", options, value => options = value);
        PluginConfiguration saved = null;

        Assert.True(MigrationRunner.Execute(files.ConfigPath, current, Json(), new[] { library }, value =>
        {
            value.Validate();
            saved = value;
        }));

        Assert.Equal(10, saved.ThunderMaxResults);
        Assert.Equal(new[] { ProviderNames.Local, ProviderNames.Thunder }, options.SubtitleFetcherOrder);
    }

    [Fact]
    public void ImportsOnlySpecifiedLegacySettingsAndKeepsOtherNewSettings()
    {
        using var files = new Fixture();
        files.Write("MeiamSub.LocalPool.json", "{\"SubtitleLibraryPaths\":\"/subtitles;/more\"}");
        files.Write("ThunderSubtitle.json", "{\"EnableAutoDownloadOnNewMedia\":false}");
        files.Write("ChickenRicePool.json", "{\"PoolBaseUrl\":\"https://legacy-pool.test\",\"RequestTimeoutSeconds\":22,\"EnableAutoDownloadOnNewMedia\":true,\"SimplifiedChineseLanguage\":\"zh-Hans\",\"TraditionalChineseLanguage\":\"zh-Hant\"}");
        files.Write("SubtitleCloudPlugin.xml", "<PluginConfiguration><ServiceUrl>http://nas.test:9198</ServiceUrl><ApiToken>synthetic-test-token</ApiToken><PathMappings>/media=/nas</PathMappings></PluginConfiguration>");
        files.Write("MeiamSub.Thunder.json", "not-json-and-must-not-be-read");
        var original = new PluginConfiguration { LocalMaxResults = 7, Proxy = new ProxyConfiguration { Username = "keep-user" } };
        PluginConfiguration saved = null;
        Assert.True(MigrationRunner.Execute(files.ConfigPath, original, Json(), Array.Empty<MigrationLibrary>(), c => saved = c));
        Assert.Equal("/subtitles;/more", saved.LocalPaths);
        Assert.True(saved.AutoDownloadOnNewMedia);
        Assert.Equal(ChineseSubtitleLanguage.Simplified, saved.SimplifiedChineseLanguage);
        Assert.Equal(ChineseSubtitleLanguage.Traditional, saved.TraditionalChineseLanguage);
        Assert.Equal("http://nas.test:9198", saved.CloudServiceUrl);
        Assert.Equal("synthetic-test-token", saved.CloudApiToken);
        Assert.Equal("/media=/nas", saved.CloudPathMappings);
        Assert.Equal(7, saved.LocalMaxResults);
        Assert.Equal(10, saved.ThunderMaxResults);
        Assert.Equal("keep-user", saved.Proxy.Username);
        Assert.Equal(2, saved.MigrationVersion);
        Assert.Equal("", original.LocalPaths);
        Assert.Equal(0, original.MigrationVersion);
        Assert.True(File.Exists(Path.Combine(files.Directory, "MeiamSub.LocalPool.json")));
    }

    [Fact]
    public void AdditionalThunderSettingsDoNotEnableAutomation()
    {
        using var files = new Fixture();
        files.Write("ThunderSubtitle.json", "{\"EnableAutoDownloadOnNewMedia\":false}");
        files.Write("ChickenRicePool.json", "{\"EnableAutoDownloadOnNewMedia\":false}");
        files.Write("MeiamSub.Thunder.json", "{\"EnableAutoDownloadOnNewMedia\":true}");
        PluginConfiguration saved = null;
        MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), Array.Empty<MigrationLibrary>(), c => saved = c);
        Assert.False(saved.AutoDownloadOnNewMedia);
    }

    [Theory]
    [InlineData("{not-json")]
    [InlineData("{\"EnableAutoDownloadOnNewMedia\":\"invalid\"}")]
    public void MalformedOrInvalidLegacySettingsDoNotPartiallyWrite(string pool)
    {
        using var files = new Fixture();
        files.Write("MeiamSub.LocalPool.json", "{\"SubtitleLibraryPaths\":\"must-not-import\"}");
        files.Write("ChickenRicePool.json", pool);
        files.Write("SubtitleCloudPlugin.xml", "<PluginConfiguration><ApiToken>synthetic-secret-not-in-errors</ApiToken></PluginConfiguration>");
        var configWrites = 0;
        var libraryWrites = 0;
        var original = new PluginConfiguration();
        var library = new MigrationLibrary("a", new LibraryOptions { SubtitleFetcherOrder = new[] { "ThunderSubtitle" } }, _ => libraryWrites++);
        var error = Assert.Throws<MigrationException>(() => MigrationRunner.Execute(files.ConfigPath, original, Json(), new[] { library }, _ => configWrites++));
        Assert.DoesNotContain("synthetic-secret", error.ToString());
        Assert.Null(error.InnerException);
        Assert.Equal(0, configWrites);
        Assert.Equal(0, libraryWrites);
        Assert.Equal("", original.LocalPaths);
    }

    [Fact]
    public void CompletedMigrationIsIdempotentAndDoesNotOverwriteLaterUserEdits()
    {
        using var files = new Fixture();
        files.Write("MeiamSub.LocalPool.json", "{\"SubtitleLibraryPaths\":\"/old\"}");
        PluginConfiguration saved = null;
        MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), Array.Empty<MigrationLibrary>(), c => saved = c);
        saved.LocalPaths = "/user-edited";
        files.Write("MeiamSub.LocalPool.json", "broken-after-first-success");
        Assert.False(MigrationRunner.Execute(files.ConfigPath, saved, Json(), Array.Empty<MigrationLibrary>(), _ => throw new InvalidOperationException("Unexpected second write")));
        Assert.Equal("/user-edited", saved.LocalPaths);
    }

    [Fact]
    public void PendingLibraryRecoveryDoesNotReimportAlreadySavedUserSettings()
    {
        using var files = new Fixture();
        files.Write("subtitle-assistant-migration.pending", "1");
        files.Write("MeiamSub.LocalPool.json", "{\"SubtitleLibraryPaths\":\"/obsolete-legacy\"}");
        var current = new PluginConfiguration { MigrationVersion = 1, LocalPaths = "/user-edited-after-import" };
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "ThunderSubtitle" }, DisabledSubtitleFetchers = new[] { "ThunderSubtitle" } };
        var library = new MigrationLibrary("a", options, value => options = value);
        PluginConfiguration saved = null;
        Assert.True(MigrationRunner.Execute(files.ConfigPath, current, Json(), new[] { library }, value => saved = value));
        Assert.Equal("/user-edited-after-import", current.LocalPaths);
        Assert.Equal(2, saved.MigrationVersion);
        Assert.Equal("/user-edited-after-import", saved.LocalPaths);
        Assert.Equal(new[] { ProviderNames.Thunder }, options.SubtitleFetcherOrder);
        Assert.Equal(new[] { ProviderNames.Thunder }, options.DisabledSubtitleFetchers);
        Assert.False(File.Exists(Path.Combine(files.Directory, "subtitle-assistant-migration.pending")));
    }

    [Fact]
    public void LibraryOrderUsesSpecifiedOldSourcePositionAndKeepsExternalKeys()
    {
        var source = new LibraryOptions
        {
            SubtitleFetcherOrder = new[] { "External A", ProviderNames.Thunder, "MeiamSub.Thunder", "External B", "ThunderSubtitle", "MeiamSub.LocalPool", "海南鸡字幕池", "External C" },
            DisabledSubtitleFetchers = new[] { "MeiamSub.Thunder", ProviderNames.Thunder, "External disabled" },
            PreferredMetadataLanguage = "fr", SubtitleDownloadLanguages = new[] { "zh-CN" }, SaveSubtitlesWithMedia = false
        };
        var migrated = ProviderKeyMigration.Apply(source, Json());
        Assert.Equal(new[] { "External A", "External B", ProviderNames.Thunder, ProviderNames.Local, "External C" }, migrated.SubtitleFetcherOrder);
        Assert.Equal(new[] { "External disabled" }, migrated.DisabledSubtitleFetchers);
        Assert.Equal("fr", migrated.PreferredMetadataLanguage);
        Assert.Equal(source.SubtitleDownloadLanguages, migrated.SubtitleDownloadLanguages);
        Assert.False(migrated.SaveSubtitlesWithMedia);
        Assert.Contains("ThunderSubtitle", source.SubtitleFetcherOrder);
    }

    [Fact]
    public void RetiredPoolIsRemovedAndOtherDisabledSourcesRemainWithoutExtraThunderInterference()
    {
        var source = new LibraryOptions
        {
            SubtitleFetcherOrder = new[] { "MeiamSub.LocalPool", "ThunderSubtitle", "海南鸡字幕池" },
            DisabledSubtitleFetchers = new[] { "MeiamSub.LocalPool", "ThunderSubtitle", "海南鸡字幕池", "MeiamSub.Thunder", "Unknown" }
        };
        var migrated = ProviderKeyMigration.Apply(source, Json());
        Assert.Equal(new[] { ProviderNames.Local, ProviderNames.Thunder, "Unknown" }, migrated.DisabledSubtitleFetchers);
        var twice = ProviderKeyMigration.Apply(migrated, Json());
        Assert.Equal(migrated.SubtitleFetcherOrder, twice.SubtitleFetcherOrder);
        Assert.Equal(migrated.DisabledSubtitleFetchers, twice.DisabledSubtitleFetchers);
    }

    [Fact]
    public void OnlyExplicitlyProvidedOpaqueKeysAreMapped()
    {
        var source = new LibraryOptions { SubtitleFetcherOrder = new[] { "opaque-local", "unknown-native-id", "ThunderSubtitle" }, DisabledSubtitleFetchers = new[] { "opaque-local" } };
        var mapped = ProviderKeyMigration.Apply(source, Json(), new Dictionary<string, string> { ["opaque-local"] = "MeiamSub.LocalPool" });
        Assert.Equal(new[] { ProviderNames.Local, "unknown-native-id", ProviderNames.Thunder }, mapped.SubtitleFetcherOrder);
        Assert.Equal(new[] { ProviderNames.Local }, mapped.DisabledSubtitleFetchers);
    }

    [Fact]
    public void OldDisabledKeyDoesNotEraseAlreadyMigratedOrderPosition()
    {
        var source = new LibraryOptions
        {
            SubtitleFetcherOrder = new[] { "External", ProviderNames.Thunder, ProviderNames.Local },
            DisabledSubtitleFetchers = new[] { "ThunderSubtitle" }
        };
        var migrated = ProviderKeyMigration.Apply(source, Json());
        Assert.Equal(source.SubtitleFetcherOrder, migrated.SubtitleFetcherOrder);
        Assert.Equal(new[] { ProviderNames.Thunder }, migrated.DisabledSubtitleFetchers);
    }

    [Fact]
    public void LegacyXmlRejectsExternalEntitiesWithoutImportingAnything()
    {
        using var files = new Fixture();
        files.Write("external.txt", "synthetic-external-secret");
        var external = new Uri(Path.Combine(files.Directory, "external.txt")).AbsoluteUri;
        files.Write("SubtitleCloudPlugin.xml", "<!DOCTYPE PluginConfiguration [<!ENTITY token SYSTEM '" + external + "'>]><PluginConfiguration><ApiToken>&token;</ApiToken></PluginConfiguration>");
        var writes = 0;
        var error = Assert.Throws<MigrationException>(() => MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), Array.Empty<MigrationLibrary>(), _ => writes++));
        Assert.DoesNotContain("synthetic-external-secret", error.ToString());
        Assert.Equal(0, writes);
    }

    [Fact]
    public void BackupFailurePreventsEveryConfigurationAndLibraryWrite()
    {
        using var files = new Fixture();
        files.Write("subtitle-assistant-migration-backups", "block-directory-creation");
        var writes = 0;
        var library = new MigrationLibrary("a", new LibraryOptions { SubtitleFetcherOrder = new[] { "ThunderSubtitle" } }, _ => writes++);
        Assert.Throws<MigrationException>(() => MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), new[] { library }, _ => writes++));
        Assert.Equal(0, writes);
    }

    [Fact]
    public void BacksUpOriginalNewConfigAndAllAffectedLibrariesBeforeWriting()
    {
        using var files = new Fixture();
        const string originalBytes = "<new-config>synthetic-secret-original</new-config>";
        files.Write(Path.GetFileName(files.ConfigPath), originalBytes);
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "ThunderSubtitle" }, PreferredMetadataLanguage = "fr" };
        var library = new MigrationLibrary("library-a", options, _ =>
        {
            Assert.Contains(Directory.GetFiles(files.Directory, "*", SearchOption.AllDirectories), p => Path.GetFileName(p) == "new-config.original");
            Assert.Contains(Directory.GetFiles(files.Directory, "*.json", SearchOption.AllDirectories), p => Path.GetFileName(p).StartsWith("library-", StringComparison.Ordinal));
        });
        MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), new[] { library }, _ => { });
        var backup = Assert.Single(Directory.GetFiles(files.Directory, "new-config.original", SearchOption.AllDirectories));
        Assert.Equal(originalBytes, File.ReadAllText(backup));
        var libraryBackup = Assert.Single(Directory.GetFiles(files.Directory, "library-*.json", SearchOption.AllDirectories));
        Assert.Contains("ThunderSubtitle", File.ReadAllText(libraryBackup));
        Assert.Contains("fr", File.ReadAllText(libraryBackup));
    }

    [Fact]
    public void LibraryWriteFailureRollsBackAlreadyAppliedLibrariesAndNeverImportsConfig()
    {
        using var files = new Fixture();
        files.Write("MeiamSub.LocalPool.json", "{\"SubtitleLibraryPaths\":\"/legacy\"}");
        var first = new LibraryOptions { SubtitleFetcherOrder = new[] { "ThunderSubtitle" } };
        var second = new LibraryOptions { SubtitleFetcherOrder = new[] { "MeiamSub.LocalPool" } };
        var failOnce = true;
        var configWrites = 0;
        var libraries = new[] {
            new MigrationLibrary("a", first, value => first = value),
            new MigrationLibrary("b", second, value => { second = value; if (failOnce) { failOnce = false; throw new IOException("synthetic-secret-write-error"); } })
        };
        var error = Assert.Throws<MigrationException>(() => MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), libraries, _ => configWrites++));
        Assert.DoesNotContain("synthetic-secret", error.ToString());
        Assert.Equal(new[] { "ThunderSubtitle" }, first.SubtitleFetcherOrder);
        Assert.Equal(new[] { "MeiamSub.LocalPool" }, second.SubtitleFetcherOrder);
        Assert.Equal(0, configWrites);
    }

    [Fact]
    public void LibraryFailureCanRetryWithoutLosingDisabledState()
    {
        using var files = new Fixture();
        files.Write("MeiamSub.LocalPool.json", "{\"SubtitleLibraryPaths\":\"/legacy\"}");
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "ThunderSubtitle" }, DisabledSubtitleFetchers = new[] { "ThunderSubtitle" } };
        var failOnce = true;
        MigrationLibrary Target() => new MigrationLibrary("a", options, value => { options = value; if (failOnce) { failOnce = false; throw new IOException(); } });
        PluginConfiguration saved = null;
        Assert.Throws<MigrationException>(() => MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), new[] { Target() }, value => saved = value));
        Assert.Null(saved);
        MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), new[] { Target() }, value => saved = value);
        Assert.Equal(2, saved.MigrationVersion);
        Assert.Equal("/legacy", saved.LocalPaths);
        Assert.Equal(new[] { ProviderNames.Thunder }, options.SubtitleFetcherOrder);
        Assert.Equal(new[] { ProviderNames.Thunder }, options.DisabledSubtitleFetchers);
    }

    [Fact]
    public void ConfigWriteFailureRestoresLibrariesAndOriginalConfigBytes()
    {
        using var files = new Fixture();
        files.Write(Path.GetFileName(files.ConfigPath), "original-bytes");
        var original = new PluginConfiguration();
        var live = original;
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "ThunderSubtitle" } };
        var library = new MigrationLibrary("a", options, value => options = value);
        var error = Assert.Throws<MigrationException>(() => MigrationRunner.Execute(files.ConfigPath, original, Json(), new[] { library }, value =>
        {
            live = value;
            File.WriteAllText(files.ConfigPath, "partly-written-new-config");
            if (value.MigrationVersion == 2) throw new IOException("synthetic-secret");
        }));
        Assert.Equal(0, live.MigrationVersion);
        Assert.Equal(new[] { "ThunderSubtitle" }, options.SubtitleFetcherOrder);
        Assert.Equal("original-bytes", File.ReadAllText(files.ConfigPath));
        Assert.DoesNotContain("synthetic-secret", error.ToString());
    }

    [Fact]
    public void BrandNewInstallDisablesTheTwoManagedSourcesAndKeepsUnrelatedLibrariesIntact()
    {
        using var files = new Fixture();
        var libraryWrites = 0;
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "Other" } };
        var library = new MigrationLibrary("a", options, value => { options = value; libraryWrites++; });
        PluginConfiguration saved = null;
        MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(), new[] { library }, value => saved = value);
        Assert.Equal(2, saved.MigrationVersion);
        Assert.False(saved.AutoDownloadOnNewMedia);
        Assert.Equal(5, saved.LocalMaxResults);
        Assert.Equal(10, saved.ThunderMaxResults);
        Assert.Equal(1, libraryWrites);
        Assert.Equal(new[] { "Other" }, options.SubtitleFetcherOrder);
        Assert.Equal(new[] { ProviderNames.Local, ProviderNames.Thunder }, options.DisabledSubtitleFetchers);
    }

    [Fact]
    public void FreshInstallAppendsManagedDisablesAfterUnknownEntries()
    {
        using var files = new Fixture();
        var options = new LibraryOptions { DisabledSubtitleFetchers = new[] { "External" } };
        MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(),
            new[] { new MigrationLibrary("a", options, value => options = value) }, _ => { });
        Assert.Equal(new[] { "External", ProviderNames.Local, ProviderNames.Thunder }, options.DisabledSubtitleFetchers);
    }

    [Fact]
    public void ExistingLegacyConfigurationMeansAnUpgradeAndKeepsLibrarySourcesUntouched()
    {
        using var files = new Fixture();
        files.Write("MeiamSub.LocalPool.json", "{\"SubtitleLibraryPaths\":\"/old\"}");
        var options = new LibraryOptions();
        var writes = 0;
        MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(),
            new[] { new MigrationLibrary("a", options, value => { options = value; writes++; }) }, _ => { });
        Assert.Equal(0, writes);
        Assert.Empty(options.DisabledSubtitleFetchers);
    }

    [Fact]
    public void ExistingProviderKeysMeanAnUpgradeAndDoNotDisableAnything()
    {
        using var files = new Fixture();
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "ThunderSubtitle" } };
        MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration(), Json(),
            new[] { new MigrationLibrary("a", options, value => options = value) }, _ => { });
        Assert.Equal(new[] { ProviderNames.Thunder }, options.SubtitleFetcherOrder);
        Assert.Empty(options.DisabledSubtitleFetchers);
    }

    [Fact]
    public void CompletedV2InstallIsNeverTouched()
    {
        using var files = new Fixture();
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "Other" } };
        var writes = 0;
        Assert.False(MigrationRunner.Execute(files.ConfigPath, new PluginConfiguration { MigrationVersion = 2 }, Json(),
            new[] { new MigrationLibrary("a", options, value => { options = value; writes++; }) }, _ => throw new InvalidOperationException("no config write")));
        Assert.Equal(0, writes);
        Assert.Empty(options.DisabledSubtitleFetchers);
    }

    private static IJsonSerializer Json() => DispatchProxy.Create<IJsonSerializer, JsonProxy>();
    public class JsonProxy : DispatchProxy
    {
        private static readonly System.Text.Json.JsonSerializerOptions Options = new System.Text.Json.JsonSerializerOptions { PropertyNameCaseInsensitive = true };
        protected override object Invoke(MethodInfo method, object[] args)
        {
            if (method.Name == "SerializeToString") return JsonSerializer.Serialize(args[0], args[0].GetType(), Options);
            if (method.Name == "DeserializeFromString") return JsonSerializer.Deserialize((string)args[0], method.IsGenericMethod ? method.GetGenericArguments()[0] : (Type)args[1], Options);
            throw new NotSupportedException(method.Name);
        }
    }
    private sealed class Fixture : IDisposable
    {
        public string Directory { get; } = Path.Combine(Path.GetTempPath(), "subtitle-assistant-migration-" + Guid.NewGuid().ToString("N"));
        public string ConfigPath => Path.Combine(Directory, "Emby.SubtitleAssistant.xml");
        public Fixture() => System.IO.Directory.CreateDirectory(Directory);
        public void Write(string file, string text) => File.WriteAllText(Path.Combine(Directory, file), text);
        public void Dispose() => System.IO.Directory.Delete(Directory, true);
    }
}
