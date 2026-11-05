using System;
using System.IO;
using MediaBrowser.Controller;
using MediaBrowser.Controller.Plugins;
using MediaBrowser.Model.Logging;

namespace Emby.SubtitleAssistant.Web;

public sealed class WebModuleEntryPoint : IServerEntryPoint, IDisposable
{
    private readonly string _uiPath;
    private readonly ILogger _logger;

    public WebModuleEntryPoint(IServerApplicationPaths paths, ILogManager logs)
    {
        _uiPath = Path.Combine(paths.ApplicationResourcesPath, "dashboard-ui");
        _logger = logs.GetLogger(nameof(WebModuleEntryPoint));
    }

    public void Run()
    {
        try
        {
            using var stream = typeof(WebModuleEntryPoint).Assembly.GetManifestResourceStream("Emby.SubtitleAssistant.Web.subtitleassistant-menu.js");
            using var reader = new StreamReader(stream ?? throw new InvalidOperationException("Menu module missing"));
            if (!WebModuleInstaller.Install(_uiPath, reader.ReadToEnd()))
                _logger.Warn("Subtitle Assistant could not recognize the Emby web loader; cloud menu was not installed.");
        }
        catch { _logger.Warn("Subtitle Assistant cloud menu installation failed; check Emby web resource access."); }
    }

    public void Dispose()
    {
        try { WebModuleInstaller.Remove(_uiPath); }
        catch { _logger.Warn("Subtitle Assistant could not remove its cloud menu loader marker."); }
    }
}
