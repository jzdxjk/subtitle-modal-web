using System;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Plugins;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Serialization;
using MediaBrowser.Model.IO;

namespace Emby.SubtitleAssistant.Cloud;

public sealed class CloudRefreshMonitor : IServerEntryPoint, IDisposable
{
    private readonly ILibraryManager _library;
    private readonly IFileSystem _fileSystem;
    private readonly CloudApi _api;
    private readonly ILogger _logger;
    private readonly CancellationTokenSource _stop = new CancellationTokenSource();
    private readonly CancellationToken _token;
    private Timer _timer;
    private int _polling;

    public CloudRefreshMonitor(ILibraryManager library, IFileSystem fileSystem, IJsonSerializer json, ILogManager logs)
    {
        _library = library; _fileSystem = fileSystem; _api = new CloudApi(json, PluginHttpClient.Shared);
        _logger = logs.GetLogger(nameof(CloudRefreshMonitor)); _token = _stop.Token;
    }

    public void Run() => _timer = new Timer(_ => _ = PollAsync(), null, TimeSpan.FromSeconds(3), TimeSpan.FromSeconds(10));

    public void Dispose()
    {
        _timer?.Dispose(); _stop.Cancel(); _stop.Dispose();
    }

    public static bool ShouldRefresh(CloudJob job) => job?.status == "done" &&
        (job.refresh_state == "pending" || job.refresh_state == "refreshing") &&
        !string.IsNullOrWhiteSpace(job.id) && !string.IsNullOrWhiteSpace(job.emby_item_id);

    public static MetadataRefreshOptions CreateRefreshOptions(IFileSystem fileSystem) => new MetadataRefreshOptions(fileSystem)
    {
        MetadataRefreshMode = MetadataRefreshMode.Default, ImageRefreshMode = MetadataRefreshMode.ValidationOnly,
        ReplaceAllMetadata = false, ReplaceAllImages = false, EnableSubtitleDownloading = false, IsAutomated = true
    };

    private async Task PollAsync()
    {
        if (_token.IsCancellationRequested || string.IsNullOrWhiteSpace(Plugin.CurrentConfiguration.CloudServiceUrl) ||
            Interlocked.Exchange(ref _polling, 1) != 0) return;
        try
        {
            var jobs = await _api.JobsAsync(_token).ConfigureAwait(false);
            foreach (var job in jobs)
            {
                _token.ThrowIfCancellationRequested();
                if (!ShouldRefresh(job)) continue;
                try
                {
                    await _api.ReportRefreshAsync(job.id, "refreshing", "正在刷新 Emby 媒体信息", _token).ConfigureAwait(false);
                    if (!long.TryParse(job.emby_item_id, out var id)) throw new InvalidOperationException();
                    var item = _library.GetItemById(id) ?? throw new InvalidOperationException();
                    await item.RefreshMetadata(CreateRefreshOptions(_fileSystem), _token).ConfigureAwait(false);
                    await _api.ReportRefreshAsync(job.id, "success", "Emby 单项目刷新完成", _token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (_token.IsCancellationRequested) { throw; }
                catch
                {
                    _logger.Warn("Subtitle Assistant cloud item refresh failed; no media paths or backend response are logged.");
                    try { await _api.ReportRefreshAsync(job.id, "failed", "Emby 单项目刷新失败，请检查服务器日志。", _token).ConfigureAwait(false); }
                    catch (OperationCanceledException) when (_token.IsCancellationRequested) { throw; }
                    catch { _logger.Warn("Subtitle Assistant could not report cloud refresh status."); }
                }
            }
        }
        catch (OperationCanceledException) when (_token.IsCancellationRequested) { }
        catch { _logger.Warn("Subtitle Assistant cloud polling failed; check service connectivity and API token."); }
        finally { Interlocked.Exchange(ref _polling, 0); }
    }
}
