using System;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class ProviderOrderTests
{
    [Fact]
    public void ResolvesOrderFromConfiguredPositions()
    {
        using (Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Thunder" } }))
        {
            Assert.Equal(80, ProviderOrder.Resolve(ProviderKeys.Local));
            Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Thunder));
        }
        using (Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = new[] { "Thunder", "Local" } }))
        {
            Assert.Equal(80, ProviderOrder.Resolve(ProviderKeys.Thunder));
            Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Local));
        }
    }

    [Fact]
    public void FallsBackToDefaultOrderWhenConfigurationInvalid()
    {
        using var scope = Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = null });
        Assert.Equal(80, ProviderOrder.Resolve(ProviderKeys.Local));
        Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Thunder));
    }

    [Fact]
    public void ValidationFallsBackForMissingOrInvalidOrder()
    {
        new PluginConfiguration { ProviderDisplayOrder = new[] { "Thunder", "Local" } }.Validate();
        var missing = new PluginConfiguration { ProviderDisplayOrder = null };
        missing.Validate();
        Assert.Equal(new[] { "Local", "Thunder" }, missing.ProviderDisplayOrder);
        var shortOrder = new PluginConfiguration { ProviderDisplayOrder = new[] { "Thunder" } };
        shortOrder.Validate();
        Assert.Equal(new[] { "Local", "Thunder" }, shortOrder.ProviderDisplayOrder);
        var duplicate = new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Local" } };
        duplicate.Validate();
        Assert.Equal(new[] { "Local", "Thunder" }, duplicate.ProviderDisplayOrder);
        var unknown = new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Bogus" } };
        unknown.Validate();
        Assert.Equal(new[] { "Local", "Thunder" }, unknown.ProviderDisplayOrder);
    }
}
