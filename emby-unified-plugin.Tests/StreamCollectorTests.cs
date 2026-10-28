using System;
using System.Collections.Generic;
using System.IO;
using Emby.SubtitleAssistant.Automation;
using MediaBrowser.Model.Configuration;
using MediaBrowser.Model.Entities;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class StreamCollectorTests
{
    private static MediaStream Subtitle(string language, int index = 1, bool external = true)
        => new MediaStream { Type = MediaStreamType.Subtitle, Language = language, Index = index, IsExternal = external };

    [Fact]
    public void NullAndEmptySourcesYieldNoStreams()
    {
        var failures = new List<string>();
        var result = StreamCollector.Collect(() => null, _ => null, 10L, (stage, _) => failures.Add(stage));
        Assert.Empty(result);
        Assert.Empty(failures);
    }

    [Fact]
    public void ItemStreamsSurviveWhenMediaSourceLookupReturnsNothing()
    {
        var result = StreamCollector.Collect(
            () => new[] { Subtitle("zh-CN") },
            _ => Array.Empty<MediaStream>(),
            10L,
            (_, __) => { });
        Assert.Single(result);
    }

    [Fact]
    public void MediaSourceLookupOutOfRangeIsReportedInsteadOfThrown()
    {
        var failures = new List<(string Stage, Exception Error)>();
        var result = StreamCollector.Collect(
            () => Array.Empty<MediaStream>(),
            _ => throw new ArgumentOutOfRangeException("id", "media source unavailable"),
            66659L,
            (stage, error) => failures.Add((stage, error)));

        Assert.Empty(result);
        var failure = Assert.Single(failures);
        Assert.Equal(StreamCollector.MediaSourceStreamsStage, failure.Stage);
        Assert.IsType<ArgumentOutOfRangeException>(failure.Error);
    }

    [Fact]
    public void StreamLookupFailureFailsClosedForSubtitleCompletion()
    {
        var failed = false;
        var streams = StreamCollector.Collect(
            () => Array.Empty<MediaStream>(),
            _ => throw new IOException("media streams unavailable"),
            66659L,
            (_, __) => failed = true);

        Assert.True(CompletionPolicy.SkipForStreams(new LibraryOptions(),streams,failed));
    }

    [Fact]
    public void MediaSourceStreamsStillContributeWhenItemStreamsEmpty()
    {
        var result = StreamCollector.Collect(
            () => Array.Empty<MediaStream>(),
            _ => new[] { Subtitle("zh-CN", 2, false) },
            66659L,
            (_, __) => { });

        var stream = Assert.Single(result);
        Assert.False(stream.IsExternal);
        Assert.True(CompletionPolicy.SkipForStreams(new LibraryOptions(), result));
    }

    [Fact]
    public void NonPositiveInternalIdDoesNotQueryMediaSources()
    {
        var queried = false;
        var result = StreamCollector.Collect(
            () => new[] { Subtitle("jpn", 1, false) },
            _ => { queried = true; return Array.Empty<MediaStream>(); },
            0L,
            (_, __) => { });

        Assert.False(queried);
        Assert.Single(result);
    }

    [Fact]
    public void DuplicateStreamsAreCollapsed()
    {
        var shared = Subtitle("zh-CN", 3, true);
        var result = StreamCollector.Collect(
            () => new[] { shared, shared },
            _ => new[] { Subtitle("zh-CN", 3, true) },
            42L,
            (_, __) => { });

        Assert.Single(result);
    }

    [Fact]
    public void EnumerationFailureIsReportedAndKeepsEarlierStreams()
    {
        var failures = new List<string>();
        IEnumerable<MediaStream> ThrowsAfterOne()
        {
            yield return Subtitle("jpn", 1, false);
            throw new ArgumentOutOfRangeException("streams", "enumeration failed");
        }

        var result = StreamCollector.Collect(ThrowsAfterOne, _ => null, 42L, (stage, _) => failures.Add(stage));

        Assert.Single(result);
        Assert.Equal(new[] { StreamCollector.ItemStreamsStage }, failures);
    }
}
