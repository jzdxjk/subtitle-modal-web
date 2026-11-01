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
            Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Local));
            Assert.Equal(100, ProviderOrder.Resolve(ProviderKeys.Thunder));
        }
        using (Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = new[] { "Thunder", "Local" } }))
        {
            Assert.Equal(100, ProviderOrder.Resolve(ProviderKeys.Thunder));
            Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Local));
        }
        using (Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = ProviderOrder.Default }))
            Assert.Equal(80, ProviderOrder.Resolve(ProviderKeys.Pool));
    }

    [Fact]
    public void FallsBackToDefaultOrderWhenConfigurationInvalid()
    {
        using var scope = Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = null });
        Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Local));
        Assert.Equal(100, ProviderOrder.Resolve(ProviderKeys.Thunder));
        Assert.Equal(80, ProviderOrder.Resolve(ProviderKeys.Pool));
    }

    [Fact]
    public void ValidationFallsBackForMissingOrInvalidOrder()
    {
        new PluginConfiguration { ProviderDisplayOrder = new[] { "Pool", "Thunder", "Local" } }.Validate();
        var missing = new PluginConfiguration { ProviderDisplayOrder = null };
        missing.Validate();
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, missing.ProviderDisplayOrder);
        var shortOrder = new PluginConfiguration { ProviderDisplayOrder = new[] { "Thunder" } };
        shortOrder.Validate();
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, shortOrder.ProviderDisplayOrder);
        var duplicate = new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Local", "Pool" } };
        duplicate.Validate();
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, duplicate.ProviderDisplayOrder);
        var unknown = new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Bogus", "Pool" } };
        unknown.Validate();
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, unknown.ProviderDisplayOrder);
    }
}
