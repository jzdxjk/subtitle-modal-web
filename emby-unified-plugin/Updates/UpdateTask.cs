using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Common;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Serialization;
using MediaBrowser.Model.Tasks;

namespace Emby.SubtitleAssistant.Updates;

public sealed class UpdateTask : IScheduledTask
{
    private readonly IApplicationHost _host;
    private readonly IApplicationPaths _paths;
    private readonly IJsonSerializer _json;
    private readonly ILogger _logger;
    public UpdateTask(IApplicationHost host, IApplicationPaths paths, IJsonSerializer json, ILogManager logs)
    { _host = host; _paths = paths; _json = json; _logger = logs?.GetLogger(nameof(UpdateTask)); }

    public string Name => "字幕助手：检查并安装更新";
    public string Key => "SubtitleAssistantUpdate";
    public string Description => "检查正式版，校验并备份替换插件；重启时间由管理员决定。";
    public string Category => "字幕助手";
    public IEnumerable<TaskTriggerInfo> GetDefaultTriggers() => new[]
    { new TaskTriggerInfo { Type = "IntervalTrigger", IntervalTicks = TimeSpan.FromHours(24).Ticks } };

    public async Task Execute(CancellationToken cancellationToken, IProgress<double> progress)
    {
        try
        {
            var destination = Plugin.Instance?.AssemblyFilePath;
            if (string.IsNullOrWhiteSpace(destination)) destination = Path.Combine(_paths.PluginsPath, "Emby.SubtitleAssistant.dll");
            var runner = new UpdateRunner(PluginHttpClient.Shared, _json);
            var result = await runner.RunAsync(Plugin.CurrentConfiguration.UpdateManifestUrl, _host.ApplicationVersion,
                destination, typeof(Plugin).Assembly.GetName().Version, cancellationToken, progress).ConfigureAwait(false);
            if (result.Installed)
            {
                _host.NotifyPendingRestart();
                _logger?.Info("Subtitle Assistant stable update installed; original DLL backup retained. Restart is pending administrator action.");
            }
            else _logger?.Info("Subtitle Assistant update check completed; no newer compatible stable version is available.");
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
        catch
        {
            _logger?.Warn("Subtitle Assistant update failed. Check the manifest, independent proxy and plugin file permissions; no backend response or credential is logged.");
            throw new InvalidOperationException("字幕助手更新失败，请检查更新清单、独立代理和插件文件权限。原有备份会保留。");
        }
    }
}
