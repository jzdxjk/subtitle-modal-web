using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Automation;
using MediaBrowser.Model.Configuration;
using MediaBrowser.Model.Providers;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Model.Entities;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class AutomationTests
{
    private static ProviderRegistration[] Registered => new[]
    {
        new ProviderRegistration(ProviderNames.Local,"id-local"),
        new ProviderRegistration(ProviderNames.Thunder,"id-thunder"),
        new ProviderRegistration(ProviderNames.Pool,"id-pool"),
        new ProviderRegistration("OpenSubtitles","id-other")
    };

    [Fact] public void DisabledSourcesNeverParticipateAndForeignPluginsAreExcluded()
    {
        var options = new LibraryOptions { DisabledSubtitleFetchers = new[] { "id-thunder" },
            SubtitleFetcherOrder = new[] { "id-other", "id-pool", "id-local", "id-thunder" } };
        Assert.Equal(new[] { ProviderNames.Pool, ProviderNames.Local },
            CompletionPolicy.EnabledProviders(options, Registered).Select(p => p.Name));
        options.DisabledSubtitleFetchers = new[] { "id-local", ProviderNames.Thunder, "id-pool" };
        Assert.Empty(CompletionPolicy.EnabledProviders(options, Registered));
        Assert.Empty(CompletionPolicy.EnabledProviders(null, Registered));
    }

    [Fact] public void HistoricalScopeNeverIncludesPoolWhileNewMediaObeysThePoolSwitch()
    {
        var options = new LibraryOptions { SubtitleFetcherOrder = new[] { "id-pool", "id-local", "id-thunder" } };
        Assert.Equal(new[] { ProviderNames.Local, ProviderNames.Thunder },
            CompletionPolicy.EnabledProviders(options, Registered, CompletionScope.Historical).Select(p => p.Name));
        Assert.Equal(new[] { ProviderNames.Pool, ProviderNames.Local, ProviderNames.Thunder },
            CompletionPolicy.EnabledProviders(options, Registered, CompletionScope.NewMedia).Select(p => p.Name));

        options.DisabledSubtitleFetchers = new[] { ProviderNames.Pool };
        Assert.Equal(new[] { ProviderNames.Local, ProviderNames.Thunder },
            CompletionPolicy.EnabledProviders(options, Registered, CompletionScope.NewMedia).Select(p => p.Name));
        Assert.Equal(new[] { ProviderNames.Local, ProviderNames.Thunder },
            CompletionPolicy.EnabledProviders(options, Registered, CompletionScope.Historical).Select(p => p.Name));
    }

    [Fact] public async Task FailedFirstFiveCandidatesDoNotApplyDisplayLimitToCompletion()
    {
        var attempts = new List<string>();
        var candidates = Enumerable.Range(1,7).Select(i => new RemoteSubtitleInfo { Id = i.ToString() }).ToArray();
        var result = await CompletionRunner.RunAsync(new[] { Registered[0] },
            (provider, ct) => Task.FromResult(candidates),
            (candidate, ct) => { attempts.Add(candidate.Id); return Task.FromResult(candidate.Id == "6"); }, CancellationToken.None);
        Assert.True(result);
        Assert.Equal(new[] { "1","2","3","4","5","6" }, attempts);
    }

    [Fact] public async Task SourceFailureContinuesInLibraryOrderAndStopsAfterSuccess()
    {
        var sources = new[] { Registered[2], Registered[0], Registered[1] };
        var searched = new List<string>();
        var result = await CompletionRunner.RunAsync(sources, (source,ct) =>
        {
            searched.Add(source.Name);
            if (source.Name == ProviderNames.Pool) throw new InvalidOperationException("unavailable");
            return Task.FromResult(new[] { new RemoteSubtitleInfo { Id = source.Id } });
        }, (candidate,ct) => Task.FromResult(true), CancellationToken.None);
        Assert.True(result);
        Assert.Equal(new[] { ProviderNames.Pool, ProviderNames.Local }, searched);
    }

    [Fact] public async Task CancellationStopsBeforeAnotherSourceIsSearched()
    {
        using var cts = new CancellationTokenSource();
        var searched = 0;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => CompletionRunner.RunAsync(Registered,
            (source,ct) => { searched++; cts.Cancel(); ct.ThrowIfCancellationRequested(); return Task.FromResult(Array.Empty<RemoteSubtitleInfo>()); },
            (candidate,ct) => Task.FromResult(false), cts.Token));
        Assert.Equal(1, searched);
    }

    [Fact] public void NativeRequestIsolatesOneSourceAndRetainsLibraryFilters()
    {
        var options = new LibraryOptions { RequirePerfectSubtitleMatch = true, ForcedSubtitlesOnly = true, HearingImpairedSubtitlesOnly = true };
        var request = CompletionPolicy.SearchRequest("/media/SSIS-157-c-无码破解.mp4", "原始标题", TimeSpan.FromHours(2).Ticks,
            VideoContentType.Movie, "zh-CN", options, Registered[0], Registered);
        Assert.Equal("/media/SSIS-157-c-无码破解.mp4", request.MediaPath);
        Assert.True(request.SearchAllProviders);
        Assert.True(request.IsPerfectMatch);
        Assert.True(request.IsForced);
        Assert.True(request.IsHearingImpaired);
        Assert.Contains("id-other", request.DisabledSubtitleFetchers);
        Assert.Contains("id-thunder", request.DisabledSubtitleFetchers);
        Assert.Contains(ProviderNames.Pool, request.DisabledSubtitleFetchers);
        Assert.DoesNotContain("id-local", request.DisabledSubtitleFetchers);
    }

    [Fact] public void RefreshRescansSubtitlesWithoutDownloadingOrReplacingMetadata()
    {
        var options = CompletionPolicy.RefreshOptions(null);
        Assert.False(options.EnableSubtitleDownloading);
        Assert.False(options.ReplaceAllMetadata);
        Assert.False(options.ReplaceAllImages);
        Assert.True(options.IsAutomated);
    }

    [Fact] public void MaxAgeCheckHandlesDateTimeOffsetWithoutOverflowing()
    {
        var options = new LibraryOptions { SubtitleDownloadMaxAgeDays = 30 };
        Assert.False(CompletionPolicy.IsTooOld(options, DateTimeOffset.Now));
        Assert.False(CompletionPolicy.IsTooOld(options, DateTimeOffset.MinValue));
        Assert.True(CompletionPolicy.IsTooOld(options, DateTimeOffset.UtcNow.AddDays(-31)));
        Assert.False(CompletionPolicy.IsTooOld(new LibraryOptions(), DateTimeOffset.UtcNow.AddDays(-31)));
    }

    [Fact] public void ChineseSubtitleAndLibrarySkipPreferencesAreRespected()
    {
        var options = new LibraryOptions();
        var chinese = new[] { new MediaStream { Type = MediaStreamType.Subtitle, Language = "zh-CN", IsExternal = true } };
        Assert.True(CompletionPolicy.SkipForStreams(options,chinese));
        options.SkipSubtitlesIfEmbeddedSubtitlesPresent = true;
        Assert.True(CompletionPolicy.SkipForStreams(options,new[] { new MediaStream { Type = MediaStreamType.Subtitle, Language = "jpn", IsExternal = false } }));
        options.SkipSubtitlesIfEmbeddedSubtitlesPresent = false;
        Assert.False(CompletionPolicy.SkipForStreams(options,new[] { new MediaStream { Type = MediaStreamType.Audio, Language = "jpn" } }));
        options.SkipSubtitlesIfAudioTrackMatches = true;
        Assert.True(CompletionPolicy.SkipForStreams(options,new[] { new MediaStream { Type = MediaStreamType.Audio, Language = "chi" } }));
    }
}
