using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Tasks;
using MediaBrowser.Model.IO;

namespace Emby.SubtitleAssistant.Automation;

public sealed class MissingSubtitleTask : IScheduledTask
{
    private readonly ILibraryManager _library;
    private readonly SubtitleCompletionService _completion;
    private readonly ILogger _logger;
    public MissingSubtitleTask(ILibraryManager library, ISubtitleManager subtitles, IMediaSourceManager mediaSources,
        IProviderManager providers, ILibraryMonitor monitor, IFileSystem files, ILogManager logs)
    {
        _library = library; _completion = new SubtitleCompletionService(library,subtitles,mediaSources,providers,monitor,files,logs);
        _logger = logs.GetLogger(nameof(MissingSubtitleTask));
    }
    public string Name => "字幕助手：补全缺失中文字幕";
    public string Key => "SubtitleAssistantMissingSubtitles";
    public string Category => "字幕助手";
    public string Description => "历史补全仅使用媒体库启用的本地、迅雷来源，按库内顺序补全缺少中文字幕的影片；海南鸡字幕仅参与新入库自动补全。";
    public IEnumerable<TaskTriggerInfo> GetDefaultTriggers() => Array.Empty<TaskTriggerInfo>();

    public async Task Execute(CancellationToken cancellationToken, IProgress<double> progress)
    {
        var offset = 0; long total = 0; var downloaded = 0;
        progress?.Report(0);
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var page = _library.GetItemsResult(new InternalItemsQuery
            { Recursive = true, IncludeItemTypes = new[] { "Movie","Episode" }, StartIndex = offset, Limit = 100 });
            var items = page.Items ?? Array.Empty<BaseItem>();
            total = Math.Max(total,page.TotalRecordCount);
            if (items.Length == 0) break;
            foreach (var item in items)
            {
                cancellationToken.ThrowIfCancellationRequested();
                try { if (await _completion.ProcessAsync(item,CompletionScope.Historical,cancellationToken).ConfigureAwait(false)) downloaded++; }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
                catch (Exception error)
                {
                    var stage = (error as SubtitleCompletionException)?.Stage ?? "process";
                    _logger.ErrorException("Subtitle completion task item failed; stage={0}, itemId={1}, path={2}",
                        error, stage, item.Id, item.Path);
                }
                offset++; progress?.Report(total > 0 ? Math.Min(99,offset * 100d / total) : 0);
            }
            if (items.Length < 100) break;
        }
        _logger.Info("Subtitle completion finished: scanned {0}, completed {1}",offset,downloaded);
        progress?.Report(100);
    }
}
