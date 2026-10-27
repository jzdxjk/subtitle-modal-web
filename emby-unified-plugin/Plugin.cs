using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Model.Drawing;
using MediaBrowser.Model.Plugins;
using MediaBrowser.Model.Serialization;

namespace Emby.SubtitleAssistant;

public sealed class Plugin : BasePlugin<PluginConfiguration>, IHasWebPages, IHasThumbImage
{
    public static readonly Guid PluginId = new Guid("76cd4168-e0b3-4aac-8a52-5cb638121744");
    private static readonly AsyncLocal<PluginConfiguration> TestConfiguration = new AsyncLocal<PluginConfiguration>();
    private static readonly PluginConfiguration Defaults = new PluginConfiguration();
    public static Plugin Instance { get; private set; }
    public static PluginConfiguration CurrentConfiguration => TestConfiguration.Value ?? Instance?.Configuration ?? Defaults;
    public override string Name => "字幕助手";
    public override Guid Id => PluginId;
    public override string Description => "本地字幕、迅雷字幕、海南鸡字幕与字幕云，一个插件统一管理。";
    public ImageFormat ThumbImageFormat => ImageFormat.Jpg;
    public Stream GetThumbImage() => GetType().Assembly.GetManifestResourceStream($"{GetType().Namespace}.Thumb.jpg");

    public Plugin(IApplicationPaths paths, IXmlSerializer xml) : base(paths, xml) => Instance = this;

    public override void UpdateConfiguration(BasePluginConfiguration configuration)
    {
        if (!(configuration is PluginConfiguration settings)) throw new ArgumentException("无效的字幕助手配置。");
        settings.Validate();
        base.UpdateConfiguration(settings);
    }

    public IEnumerable<PluginPageInfo> GetPages() => new[]
    {
        new PluginPageInfo { Name = "subtitleassistant", DisplayName = Name, IsMainConfigPage = true,
            EmbeddedResourcePath = "Emby.SubtitleAssistant.Web.configuration.html" },
        new PluginPageInfo { Name = "subtitleassistantjs", EmbeddedResourcePath = "Emby.SubtitleAssistant.Web.configuration.js" }
    };

    internal static IDisposable OverrideConfigurationForTests(PluginConfiguration configuration)
    {
        var previous = TestConfiguration.Value;
        TestConfiguration.Value = configuration;
        return new Restore(() => TestConfiguration.Value = previous);
    }

    private sealed class Restore : IDisposable
    {
        private Action _restore;
        public Restore(Action restore) => _restore = restore;
        public void Dispose() => Interlocked.Exchange(ref _restore, null)?.Invoke();
    }
}

public static class ProviderNames
{
    public const string Local = "本地字幕";
    public const string Thunder = "迅雷字幕";
    public const string Pool = "海南鸡字幕";
}
