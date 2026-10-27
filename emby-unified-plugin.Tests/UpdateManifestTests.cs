using System;
using System.Collections.Generic;
using System.IO;
using Emby.SubtitleAssistant.Updates;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class UpdateManifestTests
{
    internal static UpdateManifest Manifest(string version = "1.0.0.1") => new UpdateManifest
    {
        version = version, download_url = "https://release.invalid/Emby.SubtitleAssistant.dll",
        sha256 = new string('a', 64), plugin_id = Plugin.PluginId.ToString(), channel = "stable",
        minimum_server_versions = new Dictionary<string, string>
        {
            ["4.8"] = "4.8.11.0", ["4.9"] = "4.9.1.80", ["4.10"] = "4.10.0.40"
        }
    };

    [Theory]
    [InlineData("4.8.11.0")]
    [InlineData("4.9.1.80")]
    [InlineData("4.9.5.0")]
    [InlineData("4.10.0.40")]
    [InlineData("4.10.2.0")]
    public void StableManifestSupportsEveryRequiredEmbyVersion(string server)
        => Assert.Equal(new Version(1, 0, 0, 1), Manifest().Validate(new Version(server)));

    [Theory]
    [InlineData("4.8.10.0")]
    [InlineData("4.9.1.79")]
    [InlineData("4.10.0.39")]
    [InlineData("4.11.0.0")]
    public void IncompatibleServerCannotInstall(string server)
        => Assert.Throws<InvalidDataException>(() => Manifest().Validate(new Version(server)));

    [Theory]
    [InlineData("1.0")]
    [InlineData("1.0.0")]
    [InlineData("1.0.0.1-rc1")]
    [InlineData("65536.0.0.1")]
    public void InvalidOrPrereleaseVersionsAreRejected(string version)
        => Assert.Throws<InvalidDataException>(() => Manifest(version).Validate(new Version(4, 9, 5, 0)));

    [Fact]
    public void ManifestMustMatchIdentityStableChannelAndAllServerFamilies()
    {
        var m = Manifest(); m.plugin_id = Guid.NewGuid().ToString();
        Assert.Throws<InvalidDataException>(() => m.Validate(new Version(4, 9, 5, 0)));
        m = Manifest(); m.channel = "beta";
        Assert.Throws<InvalidDataException>(() => m.Validate(new Version(4, 9, 5, 0)));
        m = Manifest(); m.minimum_server_versions.Remove("4.8");
        Assert.Throws<InvalidDataException>(() => m.Validate(new Version(4, 9, 5, 0)));
        m = Manifest(); m.minimum_server_versions["4.8"] = "4.9.1.80";
        Assert.Throws<InvalidDataException>(() => m.Validate(new Version(4, 9, 5, 0)));
    }
}
