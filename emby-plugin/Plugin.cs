using MediaBrowser.Common.Configuration;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Model.Serialization;
using MediaBrowser.Model.Plugins;
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

namespace SubtitleCloudPlugin;

public sealed class Plugin : BasePlugin<PluginConfiguration>, IHasWebPages
{
    public static Plugin Instance { get; private set; }
    public override string Name => "Subtitle Cloud Translation";
    public override Guid Id => new Guid("7b7a52b3-3c19-4a37-9d06-0e32e3b9c4d1");
    public override string Description => "Generate subtitles through Subtitle Cloud Translation.";
    public Plugin(IApplicationPaths applicationPaths, IXmlSerializer xmlSerializer) : base(applicationPaths, xmlSerializer) => Instance = this;
    public IEnumerable<PluginPageInfo> GetPages() => new[]
    {
        new PluginPageInfo
        {
            Name = "subtitlecloudv2",
            DisplayName = Name,
            IsMainConfigPage = true,
            EmbeddedResourcePath = GetType().Namespace + ".PluginPage.html"
        },
        new PluginPageInfo
        {
            Name = "subtitlecloudjsv2",
            EmbeddedResourcePath = GetType().Namespace + ".SubtitleCloudPage.js"
        },
    };
}

public sealed class PluginConfiguration : BasePluginConfiguration
{
    public string ServiceUrl { get; set; } = "http://10.0.0.235:9198";
    public string ApiToken { get; set; } = "";
    public string PathMappings { get; set; } = "";
}

public sealed class PluginPage { }
