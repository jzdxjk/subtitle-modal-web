using System;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class ConfigurationTests
{
    [Fact] public void EachSourceDefaultsToFiveResults()
    {
        var config = new PluginConfiguration();
        Assert.Equal(5, config.LocalMaxResults);
        Assert.Equal(5, config.ThunderMaxResults);
        Assert.Equal(5, config.PoolMaxResults);
        Assert.Equal(15, config.ThunderTimeoutSeconds);
        Assert.Equal(PluginConfiguration.OfficialPoolUrl, config.PoolUrl);
        Assert.False(config.AutoDownloadOnNewMedia);
        config.Validate();
    }

    [Theory]
    [InlineData(0)] [InlineData(-1)]
    public void RejectsNonPositiveDisplayLimit(int value)
    {
        var config = new PluginConfiguration { LocalMaxResults = value };
        Assert.Throws<ArgumentException>(() => config.Validate());
    }

    [Theory]
    [InlineData(0)] [InlineData(121)]
    public void RejectsOutOfRangeThunderTimeout(int value)
    {
        var config = new PluginConfiguration { ThunderTimeoutSeconds = value };
        Assert.Throws<ArgumentException>(() => config.Validate());
    }

    [Fact] public void ProxyDefaultsKeepCloudAndPrivateAddressesDirect()
    {
        var proxy = new PluginConfiguration().Proxy;
        Assert.False(proxy.Enabled);
        Assert.True(proxy.Thunder);
        Assert.True(proxy.Pool);
        Assert.True(proxy.Updates);
        Assert.False(proxy.Cloud);
        Assert.True(proxy.BypassLocal);
    }

    [Theory]
    [InlineData("http://127.0.0.1:7890")]
    [InlineData("socks5://proxy.example:1080")]
    public void AcceptsSupportedProxySchemes(string address)
    {
        var config = new PluginConfiguration();
        config.Proxy.Enabled = true;
        config.Proxy.Address = address;
        config.Validate();
    }

    [Theory]
    [InlineData("ftp://proxy.example")]
    [InlineData("http://user:secret@proxy.example:7890")]
    [InlineData("http://proxy.example:7890/unexpected?token=secret")]
    public void RejectsInvalidProxyWithoutLeakingCredentials(string address)
    {
        var config = new PluginConfiguration();
        config.Proxy.Enabled = true;
        config.Proxy.Address = address;
        var error = Assert.Throws<ArgumentException>(() => config.Validate());
        Assert.DoesNotContain("secret", error.Message);
    }
}
