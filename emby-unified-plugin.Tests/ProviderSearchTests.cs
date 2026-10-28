using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using Emby.SubtitleAssistant.Providers;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Model.Providers;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class ProviderSearchTests
{
    public ProviderSearchTests() { ProviderSearchCache.Shared = new ProviderSearchCache(); }

    [Theory]
    [InlineData("SSIS-157-LTX【2021-08-19】（小宵虎南）出差和一直蔑视的中年性骚扰上司共处一室…直到早晨的绝伦性交HCUP新入社员.mp4", "SSIS-157")]
    [InlineData("SSIS-157-c-无码破解.mp4", "SSIS-157")]
    [InlineData("SAVR00143.mp4", "SAVR-00143")]
    public async Task OrdinaryThunderSearchSendsExactlyOneCleanQuery(string path, string expected)
    {
        var config = new PluginConfiguration();
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(_ => "{\"code\":0,\"data\":[]}");
        using var http = new PluginHttpClient(() => config, _ => handler);
        Assert.Empty(await new ThunderSubtitleProvider(http).Search(Request(path), CancellationToken.None));
        Assert.Equal("?name=" + expected, Uri.UnescapeDataString(Assert.Single(handler.Calls).Query));
    }

    [Fact]
    public async Task ThunderQueriesAllAliasesPrefetchesEveryCandidateAndReusesBodies()
    {
        var config = new PluginConfiguration { ThunderMaxResults = 5 };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri =>
        {
            if (uri.Host == "api-shoulei-ssl.xunlei.com")
                return JsonSerializer.Serialize(new { code = 0, data = Enumerable.Range(1, 6).Select(i => new { name = $"FC2-PPV-1234567 第{i}版.srt", url = $"https://files.test/{i}.srt", ext = "srt", duration = i == 1 ? 999000 : i * 1000, cid = "same-video-cid", gcid = "same-untrusted-gcid" }) });
            var version = int.Parse(uri.AbsolutePath.Trim('/').Split('.')[0]);
            return Srt(version, version == 1 ? 100 : 200 - version * 10);
        });
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = new ThunderSubtitleProvider(http);
        var request = Request("/media/带空格/FC2-1234567.mp4");
        var display = (await provider.Search(request, CancellationToken.None)).ToArray();
        Assert.Equal(5, display.Length);
        Assert.Equal(request.MediaPath, ProviderSupport.Decode(display[0].Id).MediaPath);
        Assert.Contains("第1版", display[0].Name); // Parsed timeline (100s) wins over the misleading API value.
        Assert.Contains("(字幕轴)", display[0].Name);
        var queries = handler.Calls.Where(x => x.Host == "api-shoulei-ssl.xunlei.com").Select(x => Uri.UnescapeDataString(x.Query)).ToArray();
        Assert.Equal(3, queries.Length);
        Assert.Contains(queries, x => x.Contains("FC2-PPV-1234567"));
        Assert.Contains(queries, x => x.Contains("FC2PPV-1234567"));
        Assert.Contains(queries, x => x.Contains("FC2-1234567"));
        Assert.Equal(6, handler.Calls.Count(x => x.Host == "files.test"));
        using (SearchExecutionContext.BeginAutomation())
            Assert.Equal(6, (await provider.Search(request, CancellationToken.None)).Count());
        using var downloaded = (await provider.GetSubtitles(display[0].Id, CancellationToken.None)).Stream;
        Assert.NotNull(downloaded);
        Assert.Equal(6, handler.Calls.Count(x => x.Host == "files.test"));
    }

    [Fact]
    public async Task ThunderDeduplicatesByContentButNeverByCidAndRejectsUnnumberedResults()
    {
        var config = new PluginConfiguration();
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri => uri.Host == "api-shoulei-ssl.xunlei.com"
            ? JsonSerializer.Serialize(new { code = 0, data = new[] {
                new { name = "SSIS-157 第一版", extraname = "", url = "https://files.test/a.srt", ext = "srt", duration = 99, cid = "same" },
                new { name = "SSIS-157 重复内容", extraname = "", url = "https://files.test/b.srt", ext = "srt", duration = 99, cid = "same" },
                new { name = "anonymous", extraname = "SSIS-157", url = "https://files.test/c.srt", ext = "srt", duration = 98, cid = "same" },
                new { name = "SSIS-158", extraname = "", url = "https://files.test/wrong.srt", ext = "srt", duration = 100, cid = "same" },
                new { name = "anonymous", extraname = "", url = "https://files.test/unknown.srt", ext = "srt", duration = 100, cid = "same" }
            } })
            : uri.AbsolutePath == "/c.srt" ? Srt(2, 100) : Srt(1, 100));
        using var http = new PluginHttpClient(() => config, _ => handler);
        var results = (await new ThunderSubtitleProvider(http).Search(Request("SSIS-157.mp4"), CancellationToken.None)).ToArray();
        Assert.Equal(2, results.Length);
        Assert.DoesNotContain(handler.Calls, x => x.AbsolutePath.Contains("wrong") || x.AbsolutePath.Contains("unknown"));
    }

    [Fact]
    public async Task NoNumberDoesNotCallAnyRemoteEndpoint()
    {
        var config = new PluginConfiguration { PoolUrl = "https://pool.test" };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(_ => throw new InvalidOperationException("Unexpected HTTP"));
        using var http = new PluginHttpClient(() => config, _ => handler);
        Assert.Empty(await new ThunderSubtitleProvider(http).Search(Request("/SSIS-157/title.mp4"), CancellationToken.None));
        Assert.Empty(await new PoolSubtitleProvider(http).Search(Request("title.mp4"), CancellationToken.None));
        Assert.Empty(handler.Calls);
    }

    [Fact]
    public async Task PoolUsesUnlimitedBatchWorkSearchAndChecksReturnedCodes()
    {
        var config = new PluginConfiguration { PoolUrl = "https://pool.test/", PoolMaxResults = 1 };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(_ => JsonSerializer.Serialize(new { items = new[] {
            new { id = "far", code = "MIUM-00123-CD2", format = "srt", duration_seconds = 80, size_bytes = 5000, sha256 = "far" },
            new { id = "near", code = "300MIUM-00123", format = "ass", duration_seconds = 99, size_bytes = 100, sha256 = "near" },
            new { id = "wrong", code = "MIUM-00124", format = "srt", duration_seconds = 100, size_bytes = 9999, sha256 = "wrong" }
        } }));
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = new PoolSubtitleProvider(http);
        var results = (await provider.Search(Request("MIUM-00123-CD1.mp4"), CancellationToken.None)).ToArray();
        Assert.Single(results);
        Assert.Equal("ass", results[0].Format);
        Assert.Equal("MIUM-00123-CD1.mp4", ProviderSupport.Decode(results[0].Id).MediaPath);
        var url = Uri.UnescapeDataString(Assert.Single(handler.Calls).Query);
        Assert.Contains("match=work", url);
        Assert.Contains("codes=300MIUM-00123", url);
        Assert.Contains("codes=MIUM-00123", url);
        Assert.Equal(2, url.Split('&').Count(x => x.StartsWith("codes=", StringComparison.Ordinal)));
        Assert.DoesNotContain("limit=", url);
        using (SearchExecutionContext.BeginAutomation())
            Assert.Equal(2, (await provider.Search(Request("MIUM-00123.mp4"), CancellationToken.None)).Count());
    }

    [Fact]
    public async Task PoolSearchDeduplicatesBackToBackIdenticalRequests()
    {
        var config = new PluginConfiguration { PoolUrl = "https://pool.test" };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(_ => JsonSerializer.Serialize(new { items = new[] {
            new { id = "one", code = "SSIS-157", format = "srt", duration_seconds = 100, size_bytes = 1000, sha256 = "hash" }
        } }));
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = new PoolSubtitleProvider(http);
        var first = (await provider.Search(Request("SSIS-157.mp4"), CancellationToken.None)).ToArray();
        var second = (await provider.Search(Request("SSIS-157.mp4"), CancellationToken.None)).ToArray();
        Assert.Single(first);
        Assert.Equal(first[0].Id, Assert.Single(second).Id);
        Assert.Single(handler.Calls);
    }

    [Fact]
    public async Task ProviderSearchCacheCoalescesConcurrentCallsAndCachesEmptyResults()
    {
        var cache = new ProviderSearchCache();
        var started = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var calls = 0;
        Func<CancellationToken, Task<IEnumerable<RemoteSubtitleInfo>>> factory = async _ =>
        {
            Interlocked.Increment(ref calls);
            started.TrySetResult(true);
            await release.Task;
            return Array.Empty<RemoteSubtitleInfo>();
        };
        var first = cache.GetOrCreateAsync("k", factory, CancellationToken.None);
        await started.Task;
        var second = cache.GetOrCreateAsync("k", factory, CancellationToken.None);
        release.SetResult(true);
        Assert.Empty(await first);
        Assert.Empty(await second);
        Assert.Equal(1, calls);
        Assert.Empty(await cache.GetOrCreateAsync("k", factory, CancellationToken.None));
        Assert.Equal(1, calls);
    }

    [Fact]
    public async Task ProviderSearchCacheExpiresAndNeverCachesFailures()
    {
        var now = new DateTimeOffset(2026,10,28,0,0,0,TimeSpan.Zero);
        var cache = new ProviderSearchCache(16, TimeSpan.FromSeconds(60), () => now);
        var calls = 0;
        Func<CancellationToken, Task<IEnumerable<RemoteSubtitleInfo>>> empty = _ =>
        {
            calls++;
            return Task.FromResult<IEnumerable<RemoteSubtitleInfo>>(Array.Empty<RemoteSubtitleInfo>());
        };
        await cache.GetOrCreateAsync("k", empty, CancellationToken.None);
        await cache.GetOrCreateAsync("k", empty, CancellationToken.None);
        Assert.Equal(1, calls);
        now = now.AddSeconds(61);
        await cache.GetOrCreateAsync("k", empty, CancellationToken.None);
        Assert.Equal(2, calls);

        var failures = 0;
        Func<CancellationToken, Task<IEnumerable<RemoteSubtitleInfo>>> fail = _ =>
        {
            failures++;
            throw new IOException("synthetic failure");
        };
        await Assert.ThrowsAsync<IOException>(() => cache.GetOrCreateAsync("f", fail, CancellationToken.None));
        await Assert.ThrowsAsync<IOException>(() => cache.GetOrCreateAsync("f", fail, CancellationToken.None));
        Assert.Equal(2, failures);
    }

    [Fact]
    public async Task ProviderSearchCacheCancellationDoesNotCancelSharedWork()
    {
        var cache = new ProviderSearchCache();
        var started = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var calls = 0;
        Func<CancellationToken, Task<IEnumerable<RemoteSubtitleInfo>>> factory = async _ =>
        {
            Interlocked.Increment(ref calls);
            started.TrySetResult(true);
            await release.Task;
            return new[] { new RemoteSubtitleInfo { Id = "1" } };
        };
        using var cancel = new CancellationTokenSource();
        var cancelled = cache.GetOrCreateAsync("k", factory, cancel.Token);
        await started.Task;
        var survivor = cache.GetOrCreateAsync("k", factory, CancellationToken.None);
        cancel.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => cancelled);
        release.SetResult(true);
        Assert.Single(await survivor);
        Assert.Equal(1, calls);
    }

    [Fact]
    public async Task LocalUsesMaximumEndRanksBeforeSizeAndDisplayLimitDoesNotLimitAutomation()
    {
        var root = Path.Combine(Path.GetTempPath(), "subtitle-assistant-provider-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllText(Path.Combine(root, "SSIS-157-CD2.ass"), "[Events]\nDialogue: 0,0:00:01.00,0:01:39.00,Default,,0,0,0,,中文字幕");
            File.WriteAllText(Path.Combine(root, "SSIS-157.srt"), Srt(1, 80) + new string('字', 1000));
            File.WriteAllText(Path.Combine(root, "SSIS-158.srt"), Srt(1, 100));
            var config = new PluginConfiguration { LocalPaths = root, LocalMaxResults = 1 };
            using var scope = Plugin.OverrideConfigurationForTests(config);
            var provider = new LocalSubtitleProvider(null);
            var result = Assert.Single(await provider.Search(Request("SSIS-157-c-无码破解.mp4"), CancellationToken.None));
            Assert.Equal("ass", result.Format);
            Assert.Equal("SSIS-157-c-无码破解.mp4", ProviderSupport.Decode(result.Id).MediaPath);
            using (SearchExecutionContext.BeginAutomation())
                Assert.Equal(2, (await provider.Search(Request("SSIS-157.mp4"), CancellationToken.None)).Count());
            using var body = (await provider.GetSubtitles(result.Id, CancellationToken.None)).Stream;
            Assert.NotNull(body);
        }
        finally { Directory.Delete(root, true); }
    }

    [Fact]
    public async Task PrefetchHasFourSlotsAndCompletesAllItemsBeforeDisplayTruncation()
    {
        var config = new PluginConfiguration { ThunderMaxResults = 1 };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var active = 0;
        var peak = 0;
        var completed = 0;
        var handler = new AsyncFixtureHandler(async (uri, token) =>
        {
            if (uri.Host == "api-shoulei-ssl.xunlei.com")
                return JsonSerializer.Serialize(new { code = 0, data = Enumerable.Range(1, 10).Select(i => new { name = $"SSIS-157 第{i}版", url = $"https://parallel.test/{i}.srt", ext = "srt", duration = i }) });
            var current = Interlocked.Increment(ref active);
            int previous;
            do { previous = peak; } while (current > previous && Interlocked.CompareExchange(ref peak, current, previous) != previous);
            try { await Task.Delay(20, token); Interlocked.Increment(ref completed); return Srt(int.Parse(uri.AbsolutePath.Trim('/').Split('.')[0]), 100); }
            finally { Interlocked.Decrement(ref active); }
        });
        using var http = new PluginHttpClient(() => config, _ => handler);
        Assert.Single(await new ThunderSubtitleProvider(http).Search(Request("SSIS-157.mp4"), CancellationToken.None));
        Assert.Equal(10, completed);
        Assert.Equal(4, peak);
    }

    [Fact]
    public async Task SearchCancellationIsPropagated()
    {
        var config = new PluginConfiguration();
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new AsyncFixtureHandler(async (_, token) => { await Task.Delay(10000, token); return ""; });
        using var http = new PluginHttpClient(() => config, _ => handler);
        using var cancel = new CancellationTokenSource(20);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new ThunderSubtitleProvider(http).Search(Request("SSIS-157.mp4"), cancel.Token));
    }

    [Fact]
    public async Task LocalDownloadsCannotEscapeConfiguredRoots()
    {
        var config = new PluginConfiguration { LocalPaths = Path.GetTempPath() };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var payload = new DownloadPayload { Path = Path.Combine(Path.GetPathRoot(Path.GetTempPath()), "outside.srt"), Format = "srt", Name = "outside.srt" };
        await Assert.ThrowsAnyAsync<UnauthorizedAccessException>(() => new LocalSubtitleProvider(null).GetSubtitles(ProviderSupport.Encode(payload), CancellationToken.None));
    }

    [Fact]
    public async Task ChineseSearchKeepsDialogueWithSmallJapaneseNickname()
    {
        var directory = Path.Combine(Path.GetTempPath(), "subtitle-assistant-bilingual-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            File.WriteAllText(Path.Combine(directory, "SSIS-157.srt"), "1\n00:00:01,000 --> 00:00:05,000\n这是中文字幕。人物昵称：あい。");
            using var scope = Plugin.OverrideConfigurationForTests(new PluginConfiguration { LocalPaths = directory });
            var result = Assert.Single(await new LocalSubtitleProvider(null).Search(Request("SSIS-157.mp4"), CancellationToken.None));
            Assert.Contains("语言:中文", result.Name);
        }
        finally { Directory.Delete(directory, true); }
    }

    [Fact]
    public async Task ZipEntriesWithConflictingNumbersAreExcluded()
    {
        var root = Path.Combine(Path.GetTempPath(), "subtitle-assistant-zip-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            using (var output = File.Create(Path.Combine(root, "SSIS-157.zip")))
            using (var archive = new System.IO.Compression.ZipArchive(output, System.IO.Compression.ZipArchiveMode.Create))
            {
                using var writer = new StreamWriter(archive.CreateEntry("SSIS-157 SSIS-158.srt").Open());
                writer.Write(Srt(1, 100));
            }
            using var config = Plugin.OverrideConfigurationForTests(new PluginConfiguration { LocalPaths = root });
            Assert.Empty(await new LocalSubtitleProvider(null).Search(Request("SSIS-157.mp4"), CancellationToken.None));
        }
        finally { Directory.Delete(root, true); }
    }

    [Fact]
    public async Task ContentDeduplicationRetainsAlternateDownloadLocations()
    {
        var expected = Srt(1, 100);
        var hash = SubtitleContent.Hash(Encoding.UTF8.GetBytes(expected));
        SubtitleCandidate Candidate(string url) => new SubtitleCandidate { ContentHash = hash, Format = "srt", Language = "chi", DownloadUrl = url,
            Id = ProviderSupport.Encode(new DownloadPayload { Url = url, Format = "srt", Language = "chi", ContentHash = hash, Name = "SSIS-157.srt" }) };
        var result = Assert.Single(ProviderSupport.Deduplicate(new[] { Candidate("https://fallback.test/a.srt"), Candidate("https://fallback.test/b.srt") }));
        var config = new PluginConfiguration();
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri => uri.AbsolutePath == "/a.srt" ? throw new HttpRequestException("First location expired") : expected);
        using var http = new PluginHttpClient(() => config, _ => handler);
        using var response = (await new ThunderSubtitleProvider(http).GetSubtitles(result.Id, CancellationToken.None)).Stream;
        using var reader = new StreamReader(response);
        Assert.Equal(expected, await reader.ReadToEndAsync());
        Assert.Equal(2, handler.Calls.Count);
    }

    [Fact]
    public async Task TamperedDownloadIdIsRejectedBeforeAnyNetworkRequest()
    {
        var config = new PluginConfiguration { PoolUrl = "https://pool.test" };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(_ => throw new InvalidOperationException("Forged ID reached HTTP"));
        using var http = new PluginHttpClient(() => config, _ => handler);
        var id = ProviderSupport.Encode(new DownloadPayload { Url = "https://issued.test/sub.srt", PoolId = "issued", Format = "srt", Language = "chi" });
        var segments = id.Substring(4).Split('.');
        var json = Encoding.UTF8.GetString(Convert.FromBase64String(segments[0].Replace('-', '+').Replace('_', '/') + new string('=', (4 - segments[0].Length % 4) % 4)));
        json = json.Replace("issued.test", "127.0.0.1");
        var forged = "sa1." + Convert.ToBase64String(Encoding.UTF8.GetBytes(json)).TrimEnd('=').Replace('+', '-').Replace('/', '_') + (segments.Length > 1 ? "." + segments[1] : "");
        await Assert.ThrowsAnyAsync<InvalidDataException>(() => new ThunderSubtitleProvider(http).GetSubtitles(forged, CancellationToken.None));
        await Assert.ThrowsAnyAsync<InvalidDataException>(() => new PoolSubtitleProvider(http).GetSubtitles(forged, CancellationToken.None));
        Assert.Empty(handler.Calls);
    }

    [Fact]
    public async Task ValidSignedDownloadSurvivesNativeOuterPrefix()
    {
        var config = new PluginConfiguration();
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var content = Srt(1, 100);
        var handler = new FixtureHandler(_ => content);
        using var http = new PluginHttpClient(() => config, _ => handler);
        var id = ProviderSupport.Encode(new DownloadPayload { Url = "https://issued.test/sub.srt", Format = "srt", Language = "chi", Name = "SSIS-157.srt" });
        using var stream = (await new ThunderSubtitleProvider(http).GetSubtitles("native-prefix_zh-CN_" + id, CancellationToken.None)).Stream;
        using var reader = new StreamReader(stream);
        Assert.Equal(content, await reader.ReadToEndAsync());
    }

    [Fact]
    public async Task LocalDownloadRejectsNonSubtitleExtensionEvenInsideRoot()
    {
        var directory = Path.Combine(Path.GetTempPath(), "subtitle-assistant-extension-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var path = Path.Combine(directory, "SSIS-157.txt");
            File.WriteAllText(path, Srt(1, 100));
            using var config = Plugin.OverrideConfigurationForTests(new PluginConfiguration { LocalPaths = directory });
            var id = ProviderSupport.Encode(new DownloadPayload { Path = path, Format = "srt", Name = "SSIS-157.txt" });
            await Assert.ThrowsAnyAsync<InvalidDataException>(() => new LocalSubtitleProvider(null).GetSubtitles(id, CancellationToken.None));
        }
        finally { Directory.Delete(directory, true); }
    }

    [Fact]
    public void SearchResultSizesUseKilobytesWithOneDecimal()
    {
        using var config = Plugin.OverrideConfigurationForTests(new PluginConfiguration());
        var candidates = new[]
        {
            new SubtitleCandidate { Name = "a", DurationSeconds = 100, SizeBytes = 125440, StableOrder = 0 },
            new SubtitleCandidate { Name = "b", DurationSeconds = 100, SizeBytes = 512, StableOrder = 1 },
            new SubtitleCandidate { Name = "c", DurationSeconds = 100, SizeBytes = 0, StableOrder = 2 },
            new SubtitleCandidate { Name = "d", DurationSeconds = 100, SizeBytes = null, StableOrder = 3 }
        };
        var infos = ProviderSupport.Complete(candidates, Request("SSIS-157.mp4"), ProviderNames.Local, 5, "字幕轴").ToArray();
        Assert.Contains(infos, x => x.Name.Contains("大小:122.5 KB"));
        Assert.Contains(infos, x => x.Name.Contains("大小:0.5 KB"));
        Assert.Contains(infos, x => x.Name.Contains("大小:0.0 KB"));
        Assert.Contains(infos, x => x.Name.Contains("大小:unknown"));
        Assert.DoesNotContain(infos, x => x.Name.Contains("大小:0 B") || x.Name.Contains("大小:125440 B"));
    }

    [Fact]
    public void CompleteUsesPerCandidateDurationSource()
    {
        var candidates = new[]
        {
            new SubtitleCandidate { Name = "timeline", DurationSeconds = 100, DurationSource = "字幕轴", SizeBytes = 1024, StableOrder = 0 },
            new SubtitleCandidate { Name = "api", DurationSeconds = 99, DurationSource = "迅雷API", SizeBytes = 1024, StableOrder = 1 }
        };
        var infos = ProviderSupport.Complete(candidates, Request("SSIS-157.mp4"), ProviderNames.Thunder, 5, "迅雷API").ToArray();
        Assert.Contains(infos, x => x.Name.Contains("时长:00:01:40(字幕轴)"));
        Assert.Contains(infos, x => x.Name.Contains("时长:00:01:39(迅雷API)"));
    }

    [Fact]
    public async Task ThunderUsesApiMillisecondsWhenTimelineUnavailable()
    {
        var config = new PluginConfiguration { ThunderMaxResults = 5 };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri =>
        {
            if (uri.Host == "api-shoulei-ssl.xunlei.com")
                return JsonSerializer.Serialize(new { code = 0, data = new[] {
                    new { name = "SSIS-157 A.srt", url = "https://files.test/ok.srt", ext = "srt", duration = (double?)100000 },
                    new { name = "SSIS-157 B.srt", url = "https://files.test/none.srt", ext = "srt", duration = (double?)null }
                } });
            throw new HttpRequestException("subtitle body unavailable");
        });
        using var http = new PluginHttpClient(() => config, _ => handler);
        var results = (await new ThunderSubtitleProvider(http).Search(Request("SSIS-157.mp4"), CancellationToken.None)).ToArray();
        Assert.NotEmpty(results);
        Assert.Contains(results, x => x.Name.Contains("00:01:40(迅雷API)"));
        Assert.Contains(results, x => x.Name.Contains("unknown(迅雷API)"));
    }

    private static SubtitleSearchRequest Request(string path) => new SubtitleSearchRequest { MediaPath = path, Language = "chi", RuntimeTicks = TimeSpan.FromSeconds(100).Ticks };
    private static string Srt(int version, int end) => $"1\n00:00:01,000 --> 00:{end / 60:00}:{end % 60:00},000\n中文字幕第{version}版";
    private sealed class FixtureHandler : HttpMessageHandler
    {
        private readonly Func<Uri, string> _response;
        public ConcurrentQueue<Uri> Calls { get; } = new();
        public FixtureHandler(Func<Uri, string> response) => _response = response;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls.Enqueue(request.RequestUri);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(_response(request.RequestUri), Encoding.UTF8) });
        }
    }
    private sealed class AsyncFixtureHandler : HttpMessageHandler
    {
        private readonly Func<Uri, CancellationToken, Task<string>> _response;
        public AsyncFixtureHandler(Func<Uri, CancellationToken, Task<string>> response) => _response = response;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(await _response(request.RequestUri, cancellationToken), Encoding.UTF8) };
    }
}
