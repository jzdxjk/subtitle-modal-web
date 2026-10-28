using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Model.Configuration;
using MediaBrowser.Model.Providers;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Library;
using MediaBrowser.Model.Entities;

namespace Emby.SubtitleAssistant.Automation;

public sealed class ProviderRegistration
{
    public string Name { get; }
    public string Id { get; }
    public ProviderRegistration(string name, string id) { Name = name; Id = id; }
}

public enum CompletionScope
{
    // Historical and newly added media use only enabled native Local and Thunder sources.
    Historical,
    NewMedia
}

public static class CompletionPolicy
{
    public static IReadOnlyList<ProviderRegistration> EnabledProviders(LibraryOptions options, IEnumerable<ProviderRegistration> registered,
        CompletionScope scope = CompletionScope.NewMedia)
    {
        if (options == null) return Array.Empty<ProviderRegistration>();
        var own = new[] { ProviderNames.Local, ProviderNames.Thunder };
        var disabled = new HashSet<string>(options.DisabledSubtitleFetchers ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        var order = options.SubtitleFetcherOrder ?? Array.Empty<string>();
        return (registered ?? Array.Empty<ProviderRegistration>())
            .Where(p => own.Contains(p.Name) && !disabled.Contains(p.Name) && !disabled.Contains(p.Id))
            .GroupBy(p => p.Name).Select(group => group.First())
            .OrderBy(p => { var index = Array.FindIndex(order, key => SameKey(key,p)); return index < 0 ? int.MaxValue : index; })
            .ThenBy(p => Array.IndexOf(own,p.Name)).ToArray();
    }

    internal static bool SameKey(string value, ProviderRegistration source) =>
        string.Equals(value,source.Name,StringComparison.OrdinalIgnoreCase) || string.Equals(value,source.Id,StringComparison.OrdinalIgnoreCase);

    public static SubtitleSearchRequest SearchRequest(string path, string name, long? runtimeTicks, VideoContentType type,
        string language, LibraryOptions options, ProviderRegistration source, IEnumerable<ProviderRegistration> registered)
    {
        var disabled = (registered ?? Array.Empty<ProviderRegistration>()).Where(p => !SameKey(p.Id,source) && !SameKey(p.Name,source))
            .SelectMany(p => new[] { p.Id,p.Name }).Concat(options.DisabledSubtitleFetchers ?? Array.Empty<string>())
            .Where(value => !string.IsNullOrEmpty(value)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        return new SubtitleSearchRequest
        {
            MediaPath = path, Name = name, RuntimeTicks = runtimeTicks, ContentType = type, Language = language,
            SearchAllProviders = true, DisabledSubtitleFetchers = disabled, SubtitleFetcherOrder = new[] { source.Id,source.Name },
            IsPerfectMatch = options.RequirePerfectSubtitleMatch,
            IsForced = options.ForcedSubtitlesOnly ? true : (bool?)null,
            IsHearingImpaired = options.HearingImpairedSubtitlesOnly ? true : (bool?)null
        };
    }

    public static MetadataRefreshOptions RefreshOptions(IDirectoryService directories) => new MetadataRefreshOptions(directories)
    {
        EnableSubtitleDownloading = false, ReplaceAllMetadata = false, ReplaceAllImages = false,
        MetadataRefreshMode = MetadataRefreshMode.Default, ImageRefreshMode = MetadataRefreshMode.ValidationOnly, IsAutomated = true
    };

    public static bool IsChinese(string language)
    {
        var value = (language ?? "").Trim().ToLowerInvariant();
        return value == "chi" || value == "zho" || value == "zh" || value.StartsWith("zh-",StringComparison.Ordinal);
    }

    public static bool SkipForStreams(LibraryOptions options, IEnumerable<MediaStream> streams, bool streamLookupFailed = false)
    {
        if (options == null || streamLookupFailed) return true;
        var items = (streams ?? Array.Empty<MediaStream>()).Where(s => s != null).ToArray();
        return items.Any(s => s.Type == MediaStreamType.Subtitle) ||
            (options.SkipSubtitlesIfAudioTrackMatches && items.Any(s => s.Type == MediaStreamType.Audio && IsChinese(s.Language)));
    }

    // DateCreated is a DateTimeOffset; comparing it to DateTime.MinValue would convert that
    // local-time constant to DateTimeOffset and overflow on UTC+ offsets.
    public static bool IsTooOld(LibraryOptions options, DateTimeOffset created)
    {
        if (options == null || options.SubtitleDownloadMaxAgeDays <= 0) return false;
        if (created <= DateTimeOffset.MinValue) return false;
        return DateTimeOffset.UtcNow - created.ToUniversalTime() > TimeSpan.FromDays(options.SubtitleDownloadMaxAgeDays);
    }
}

public static class CompletionRunner
{
    public static async Task<bool> RunAsync(IEnumerable<ProviderRegistration> providers,
        Func<ProviderRegistration,CancellationToken,Task<RemoteSubtitleInfo[]>> search,
        Func<RemoteSubtitleInfo,CancellationToken,Task<bool>> download, CancellationToken ct)
    {
        foreach (var provider in providers)
        {
            ct.ThrowIfCancellationRequested();
            RemoteSubtitleInfo[] candidates;
            try { candidates = await search(provider,ct).ConfigureAwait(false); }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
            catch { continue; }
            foreach (var candidate in candidates ?? Array.Empty<RemoteSubtitleInfo>())
            {
                ct.ThrowIfCancellationRequested();
                if (candidate == null || string.IsNullOrEmpty(candidate.Id)) continue;
                try { if (await download(candidate,ct).ConfigureAwait(false)) return true; }
                catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
                catch { }
            }
        }
        return false;
    }
}
