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
    public void PoolUrlIsFixedAndHiddenAndThunderTimeoutRoundTrips()
    {
        var current = new PluginConfiguration { PoolUrl = "https://legacy-pool.example", ThunderTimeoutSeconds = 33 };
        var snapshot = SettingsEditor.Snapshot(current);
        Assert.Null(typeof(SettingsSnapshot).GetProperty("PoolUrl"));
        var unchanged = SettingsEditor.Apply(current, new SaveSettingsRequest { LocalMaxResults = 4 });
        Assert.Equal(PluginConfiguration.OfficialPoolUrl, unchanged.PoolUrl);
        Assert.Equal(33, unchanged.ThunderTimeoutSeconds);
        var updated = SettingsEditor.Apply(current, new SaveSettingsRequest { ThunderTimeoutSeconds = 25 });
        Assert.Equal(PluginConfiguration.OfficialPoolUrl, updated.PoolUrl);
        Assert.Equal(25, updated.ThunderTimeoutSeconds);
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
}
