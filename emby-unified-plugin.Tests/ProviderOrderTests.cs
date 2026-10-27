using System;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class ProviderOrderTests
{
    [Fact]
    public void ResolvesOrderFromConfiguredPositions()
    {
        using (Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Thunder", "Pool" } }))
        {
            Assert.Equal(80, ProviderOrder.Resolve(ProviderKeys.Local));
            Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Thunder));
            Assert.Equal(100, ProviderOrder.Resolve(ProviderKeys.Pool));
        }
        using (Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = new[] { "Pool", "Local", "Thunder" } }))
        {
            Assert.Equal(80, ProviderOrder.Resolve(ProviderKeys.Pool));
            Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Local));
            Assert.Equal(100, ProviderOrder.Resolve(ProviderKeys.Thunder));
        }
    }

    [Fact]
    public void FallsBackToDefaultOrderWhenConfigurationInvalid()
    {
        using var scope = Plugin.OverrideConfigurationForTests(new PluginConfiguration { ProviderDisplayOrder = null });
        Assert.Equal(80, ProviderOrder.Resolve(ProviderKeys.Pool));
        Assert.Equal(90, ProviderOrder.Resolve(ProviderKeys.Local));
        Assert.Equal(100, ProviderOrder.Resolve(ProviderKeys.Thunder));
    }

    [Fact]
    public void ValidationFallsBackForMissingOrInvalidOrder()
    {
        new PluginConfiguration { ProviderDisplayOrder = new[] { "Thunder", "Pool", "Local" } }.Validate();
        var missing = new PluginConfiguration { ProviderDisplayOrder = null };
        missing.Validate();
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, missing.ProviderDisplayOrder);
        var shortOrder = new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Thunder" } };
        shortOrder.Validate();
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, shortOrder.ProviderDisplayOrder);
        var duplicate = new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Local", "Pool" } };
        duplicate.Validate();
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, duplicate.ProviderDisplayOrder);
        var unknown = new PluginConfiguration { ProviderDisplayOrder = new[] { "Local", "Thunder", "Bogus" } };
        unknown.Validate();
        Assert.Equal(new[] { "Pool", "Local", "Thunder" }, unknown.ProviderDisplayOrder);
    }
}
