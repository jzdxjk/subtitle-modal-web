using System;
using System.Collections.Concurrent;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Plugins;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.IO;

namespace Emby.SubtitleAssistant.Automation;

public sealed class AutomationEntryPoint : IServerEntryPoint, IDisposable
{
    private readonly ILibraryManager _library;
    private readonly ISubtitleManager _subtitles;
    private readonly SubtitleCompletionService _completion;
    private readonly ILogger _logger;
    private readonly CancellationTokenSource _shutdown = new CancellationTokenSource();
    private readonly ConcurrentDictionary<Guid,byte> _queued = new ConcurrentDictionary<Guid,byte>();

    public AutomationEntryPoint(ILibraryManager library, ISubtitleManager subtitles, IMediaSourceManager mediaSources,
        IProviderManager providers, ILibraryMonitor monitor, IFileSystem files, ILogManager logs)
    {
        _library = library; _subtitles = subtitles;
        _completion = new SubtitleCompletionService(library,subtitles,mediaSources,providers,monitor,files,logs);
        _logger = logs.GetLogger(nameof(AutomationEntryPoint));
    }
    public void Run() { _library.ItemAdded += Added; DownloadWriteObserver.Factory = ObserveDownload; }

    private void Added(object sender, ItemChangeEventArgs e)
    {
        var item = e?.Item;
        if (!Plugin.CurrentConfiguration.AutoDownloadOnNewMedia || !SubtitleCompletionService.Eligible(item)) return;
        try
        {
            if (!_completion.HasEnabledSource(item) || !_queued.TryAdd(item.Id,0)) return;
            _ = AfterDelayAsync(item.Id,_shutdown.Token);
        }
        catch (Exception error) { _logger.Warn("Subtitle completion queue failed ({0})",error.GetType().Name); }
    }

    private async Task AfterDelayAsync(Guid id, CancellationToken ct)
    {
        var stage = "delay";
        BaseItem item = null;
        try
        {
            await Task.Delay(TimeSpan.FromSeconds(60),ct).ConfigureAwait(false);
            if (Plugin.CurrentConfiguration.AutoDownloadOnNewMedia)
            {
                stage = "load-item";
                item = _library.GetItemById(id);
                if (item == null)
                {
                    _logger.Warn("Subtitle completion skipped; item {0} no longer exists",id);
                    return;
                }
                stage = "process";
                await _completion.ProcessAsync(item,CompletionScope.NewMedia,ct).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
        catch (Exception error)
        {
            var failedStage = (error as SubtitleCompletionException)?.Stage ?? stage;
            _logger.ErrorException("Subtitle completion failed; stage={0}, itemId={1}, path={2}",
                error, failedStage, item?.Id ?? id, item?.Path ?? "(unknown)");
        }
        finally { _queued.TryRemove(id,out _); }
    }

    private Stream ObserveDownload(Stream stream, string mediaPath)
    {
        if (_shutdown.IsCancellationRequested) return stream;
        try
        {
            var item = _library.GetItemList(new InternalItemsQuery { Path = mediaPath, Recursive = true, Limit = 1 }).FirstOrDefault();
            if (item == null) return stream;
            return DownloadWriteObserver.Track(stream,new[] { Path.GetDirectoryName(item.Path),item.GetInternalMetadataPath() },
                Path.GetFileNameWithoutExtension(item.Path),() => { _ = RefreshDownloadedAsync(item); });
        }
        catch (Exception error) { _logger.Warn("Subtitle post-download observation unavailable ({0})",error.GetType().Name); return stream; }
    }

    private async Task RefreshDownloadedAsync(MediaBrowser.Controller.Entities.BaseItem item)
    {
        try { await _completion.RefreshAsync(item,_shutdown.Token).ConfigureAwait(false); }
        catch (OperationCanceledException) when (_shutdown.IsCancellationRequested) { }
        catch (Exception error) { _logger.Warn("Subtitle post-download refresh failed ({0})",error.GetType().Name); }
    }

    public void Dispose()
    {
        _library.ItemAdded -= Added;
        if (DownloadWriteObserver.Factory == ObserveDownload) DownloadWriteObserver.Factory = null;
        _shutdown.Cancel(); _shutdown.Dispose();
    }
}
