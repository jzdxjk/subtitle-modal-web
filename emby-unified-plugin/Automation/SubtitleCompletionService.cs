using System;
using System.Collections.Concurrent;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Entities.TV;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Model.Configuration;
using MediaBrowser.Model.Entities;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Providers;
using MediaBrowser.Model.IO;

namespace Emby.SubtitleAssistant.Automation;

internal sealed class SubtitleCompletionService
{
    private static readonly ConcurrentDictionary<Guid,byte> Active = new ConcurrentDictionary<Guid,byte>();
    private readonly ILibraryManager _library;
    private readonly ISubtitleManager _subtitles;
    private readonly IMediaSourceManager _mediaSources;
    private readonly IProviderManager _providers;
    private readonly IFileSystem _files;
    private readonly ILogger _logger;

    internal SubtitleCompletionService(ILibraryManager library, ISubtitleManager subtitles, IMediaSourceManager mediaSources,
        IProviderManager providers, ILibraryMonitor monitor, IFileSystem files, ILogManager logs)
    {
        _library = library; _subtitles = subtitles; _mediaSources = mediaSources; _providers = providers;
        _files = files; _logger = logs.GetLogger(nameof(SubtitleCompletionService));
    }

    internal bool HasEnabledSource(BaseItem item)
    {
        if (!Eligible(item)) return false;
        var options = _library.GetLibraryOptions(item);
        return CompletionPolicy.EnabledProviders(options, Registrations(item)).Count != 0;
    }

    internal static bool Eligible(BaseItem item) => (item is Movie || item is Episode) &&
        !string.IsNullOrWhiteSpace(item.Path) && MediaIdentifier.TryParse(item.Path) != null;

    private ProviderRegistration[] Registrations(BaseItem item) => (_subtitles.GetSupportedProviders(item) ?? Array.Empty<SubtitleProviderInfo>())
        .Select(p => new ProviderRegistration(p.Name,p.Id)).ToArray();

    internal async Task<bool> ProcessAsync(BaseItem item, CancellationToken ct)
    {
        if (!Eligible(item) || !Active.TryAdd(item.Id,0)) return false;
        try
        {
            var options = _library.GetLibraryOptions(item);
            var all = Registrations(item);
            var enabled = CompletionPolicy.EnabledProviders(options,all);
            if (enabled.Count == 0) return false;
            var languages = options.SubtitleDownloadLanguages ?? Array.Empty<string>();
            if (languages.Length > 0 && !languages.Any(CompletionPolicy.IsChinese)) return false;
            if (options.SubtitleDownloadMaxAgeDays > 0 && item.DateCreated > DateTime.MinValue &&
                DateTime.UtcNow - item.DateCreated.ToUniversalTime() > TimeSpan.FromDays(options.SubtitleDownloadMaxAgeDays)) return false;
            if (Skip(item,options)) return false;
            var language = TargetLanguage(languages);
            using (SearchExecutionContext.BeginAutomation())
            {
                return await CompletionRunner.RunAsync(enabled, async (source,token) =>
                {
                    // Re-read toggles for every source so a configuration change cannot start a newly disabled source.
                    var current = _library.GetLibraryOptions(item);
                    if (!CompletionPolicy.EnabledProviders(current,all).Any(p => p.Name == source.Name)) return Array.Empty<RemoteSubtitleInfo>();
                    var request = CompletionPolicy.SearchRequest(item.Path,item.Name,item.RunTimeTicks,
                        item is Episode ? VideoContentType.Episode : VideoContentType.Movie,language,current,source,all);
                    try { return await _subtitles.SearchSubtitles(request,token).ConfigureAwait(false); }
                    catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
                    catch (Exception error) { _logger.Warn("Subtitle completion source failed: {0} ({1})",source.Name,error.GetType().Name); throw; }
                }, async (candidate,token) =>
                {
                    var current = _library.GetLibraryOptions(item);
                    if (Skip(item,current)) return true;
                    if (current.RequirePerfectSubtitleMatch && candidate.IsHashMatch != true) return false;
                    try
                    {
                        var saved = await _subtitles.DownloadSubtitles(item,candidate.Id,current,token).ConfigureAwait(false);
                        if (string.IsNullOrWhiteSpace(saved) || !File.Exists(saved) || new FileInfo(saved).Length == 0) return false;
                        await RefreshAsync(item,token).ConfigureAwait(false);
                        return true;
                    }
                    catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
                    catch (Exception error) { _logger.Warn("Subtitle completion download failed ({0})",error.GetType().Name); throw; }
                },ct).ConfigureAwait(false);
            }
        }
        finally { Active.TryRemove(item.Id,out _); }
    }

    private bool Skip(BaseItem item, LibraryOptions options) => CompletionPolicy.SkipForStreams(options,
        ((System.Collections.Generic.IEnumerable<MediaStream>)item.MediaStreams ?? Array.Empty<MediaStream>())
            .Concat((System.Collections.Generic.IEnumerable<MediaStream>)_mediaSources.GetMediaStreams(item.InternalId) ?? Array.Empty<MediaStream>()));

    private static string TargetLanguage(string[] languages)
    {
        var selected = languages.FirstOrDefault(CompletionPolicy.IsChinese) ?? "chi";
        if (selected.IndexOf("TW",StringComparison.OrdinalIgnoreCase) >= 0 || selected.IndexOf("HK",StringComparison.OrdinalIgnoreCase) >= 0 ||
            selected.IndexOf("Hant",StringComparison.OrdinalIgnoreCase) >= 0) return Plugin.CurrentConfiguration.TraditionalChineseLanguage;
        return selected == "chi" || selected == "zho" ? "chi" : Plugin.CurrentConfiguration.SimplifiedChineseLanguage;
    }

    internal async Task RefreshAsync(BaseItem item, CancellationToken ct)
    {
        if (item == null) return;
        await _providers.RefreshSingleItem(item,CompletionPolicy.RefreshOptions(new DirectoryService(_logger,_files)),null,
            _library.GetLibraryOptions(item) ?? new LibraryOptions(),ct).ConfigureAwait(false);
    }

    internal bool IsOwnProvider(BaseItem item, string key) => Registrations(item).Any(p =>
        (p.Name == ProviderNames.Local || p.Name == ProviderNames.Thunder || p.Name == ProviderNames.Pool) && CompletionPolicy.SameKey(key,p));
}
