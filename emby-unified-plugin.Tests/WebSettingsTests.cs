using Emby.SubtitleAssistant.Web;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class WebSettingsTests
{
    [Fact]
    public void PartialSavePreservesOtherTabsAndSecretEmptyMeansKeep()
    {
        var current = new PluginConfiguration
        {
            LocalPaths = "/existing", ThunderMaxResults = 7, CloudApiToken = "cloud-secret",
            Proxy = new ProxyConfiguration { Password = "proxy-secret", Address = "http://127.0.0.1:7890" }
        };
        var next = SettingsEditor.Apply(current, new SaveSettingsRequest
        {
            LocalMaxResults = 9, CloudApiToken = "", Proxy = new ProxySettingsUpdate { Password = "" }
        });
        Assert.Equal(9, next.LocalMaxResults);
        Assert.Equal("/existing", next.LocalPaths);
        Assert.Equal(7, next.ThunderMaxResults);
        Assert.Equal("cloud-secret", next.CloudApiToken);
        Assert.Equal("proxy-secret", next.Proxy.Password);
        Assert.Equal(5, current.LocalMaxResults);
    }

    [Fact]
    public void ExplicitSecretClearIsSupportedAndReadSnapshotHasNoSecretFields()
    {
        var current = new PluginConfiguration { CloudApiToken = "secret", Proxy = new ProxyConfiguration { Password = "password" } };
        var snapshot = SettingsEditor.Snapshot(current);
        Assert.True(snapshot.HasCloudApiToken);
        Assert.True(snapshot.Proxy.HasPassword);
        Assert.Null(snapshot.GetType().GetProperty("CloudApiToken"));
        Assert.Null(snapshot.Proxy.GetType().GetProperty("Password"));
        var cleared = SettingsEditor.Apply(current, new SaveSettingsRequest
        {
            ClearCloudApiToken = true, Proxy = new ProxySettingsUpdate { ClearPassword = true }
        });
        Assert.Equal("", cleared.CloudApiToken);
        Assert.Equal("", cleared.Proxy.Password);
    }

    [Fact]
    public void InvalidPartialUpdateDoesNotMutateExistingConfiguration()
    {
        var current = new PluginConfiguration { LocalMaxResults = 3 };
        Assert.Throws<System.ArgumentException>(() => SettingsEditor.Apply(current, new SaveSettingsRequest { LocalMaxResults = 0 }));
        Assert.Equal(3, current.LocalMaxResults);
    }

    [Fact]
    public void StaticPoolSettingsAndThunderTimeoutRoundTrip()
    {
        var current = new PluginConfiguration { ThunderTimeoutSeconds = 33, PoolMaxResults = 7, PoolTimeoutSeconds = 22,
            PoolStaticUrl = "https://static.example", Proxy = new ProxyConfiguration { Pool = false } };
        var snapshot = SettingsEditor.Snapshot(current);
        Assert.Equal("https://static.example", snapshot.PoolStaticUrl);
        Assert.Equal(7, snapshot.PoolMaxResults);
        Assert.Equal(22, snapshot.PoolTimeoutSeconds);
        Assert.False(snapshot.Proxy.Pool);
        var unchanged = SettingsEditor.Apply(current, new SaveSettingsRequest { LocalMaxResults = 4 });
        Assert.Equal("https://static.example", unchanged.PoolStaticUrl);
        Assert.False(unchanged.Proxy.Pool);
        Assert.Equal(33, unchanged.ThunderTimeoutSeconds);
        var updated = SettingsEditor.Apply(current, new SaveSettingsRequest { ThunderTimeoutSeconds = 25 });
        Assert.Equal(25, updated.ThunderTimeoutSeconds);
        var poolUpdated = SettingsEditor.Apply(current, new SaveSettingsRequest { PoolMaxResults = 9, PoolTimeoutSeconds = 30,
            PoolStaticUrl = "https://static2.example", Proxy = new ProxySettingsUpdate { Pool = true } });
        Assert.Equal(9, poolUpdated.PoolMaxResults);
        Assert.Equal(30, poolUpdated.PoolTimeoutSeconds);
        Assert.Equal("https://static2.example", poolUpdated.PoolStaticUrl);
        Assert.True(poolUpdated.Proxy.Pool);
    }

    [Fact]
    public void FixedLanguageAndManifestValuesAreHiddenAndCannotBeOverridden()
    {
        var current = new PluginConfiguration
        {
            SimplifiedChineseLanguage = "zh-Hans",
            TraditionalChineseLanguage = "zh-Hant",
            UpdateManifestUrl = "https://mirror.invalid/update.json"
        };
        var snapshot = SettingsEditor.Snapshot(current);
        Assert.Null(typeof(SettingsSnapshot).GetProperty("SimplifiedChineseLanguage"));
        Assert.Null(typeof(SettingsSnapshot).GetProperty("TraditionalChineseLanguage"));
        Assert.Null(typeof(SettingsSnapshot).GetProperty("UpdateManifestUrl"));
        var next = SettingsEditor.Apply(current, new SaveSettingsRequest
        {
            SimplifiedChineseLanguage = "ja-JP",
            TraditionalChineseLanguage = "ja-JP",
            UpdateManifestUrl = "https://attacker.invalid/update.json"
        });
        Assert.Equal(ChineseSubtitleLanguage.Simplified, next.SimplifiedChineseLanguage);
        Assert.Equal(ChineseSubtitleLanguage.Traditional, next.TraditionalChineseLanguage);
        Assert.Equal(PluginConfiguration.OfficialUpdateManifestUrl, next.UpdateManifestUrl);
    }

    [Fact]
    public void ProviderDisplayOrderRoundTripsAndRejectsInvalidUpdate()
    {
        var current = new PluginConfiguration { ProviderDisplayOrder = new[] { "Pool", "Local", "Thunder" } };
        var snapshot = SettingsEditor.Snapshot(current);
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, snapshot.ProviderDisplayOrder);
        var unchanged = SettingsEditor.Apply(current, new SaveSettingsRequest { LocalMaxResults = 4 });
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, unchanged.ProviderDisplayOrder);
        var emptyKeepsCurrent = SettingsEditor.Apply(current, new SaveSettingsRequest { ProviderDisplayOrder = new string[0] });
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, emptyKeepsCurrent.ProviderDisplayOrder);
        Assert.Equal(new[] { "Thunder", "Local", "Pool" }, SettingsEditor.Apply(current, new SaveSettingsRequest { ProviderDisplayOrder = new[] { "Thunder", "Local", "Pool" } }).ProviderDisplayOrder);
        Assert.Throws<System.ArgumentException>(() => SettingsEditor.Apply(current, new SaveSettingsRequest { ProviderDisplayOrder = new[] { "Local", "Local" } }));
        var nullSnapshot = SettingsEditor.Snapshot(new PluginConfiguration { ProviderDisplayOrder = null });
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, nullSnapshot.ProviderDisplayOrder);
    }

    [Fact]
    public void ThunderResultLimitCannotExceedTen()
    {
        var current = new PluginConfiguration();
        Assert.Equal(10, current.ThunderMaxResults);
        Assert.Throws<System.ArgumentException>(() => SettingsEditor.Apply(current, new SaveSettingsRequest { ThunderMaxResults = 11 }));
        Assert.Equal(10, current.ThunderMaxResults);
    }
}
