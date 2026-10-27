using System;
using System.IO;
using System.Linq;
using System.Reflection;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class PluginThumbnailTests
{
    [Fact]
    public void PluginImplementsThumbImageAndEmbedsCover()
    {
        var assembly = Assembly.Load("Emby.SubtitleAssistant");
        var pluginType = assembly.GetType("Emby.SubtitleAssistant.Plugin");
        Assert.NotNull(pluginType);
        Assert.Contains(pluginType.GetInterfaces(), i => i.Name == "IHasThumbImage");
        var stream = assembly.GetManifestResourceStream("Emby.SubtitleAssistant.Thumb.jpg");
        Assert.NotNull(stream);
        using (stream) Assert.True(stream.Length > 0);
    }
}
