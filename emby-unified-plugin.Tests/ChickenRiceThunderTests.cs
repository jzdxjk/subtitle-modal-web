using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using Emby.SubtitleAssistant.Providers;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class ChickenRiceThunderTests
{
    public ChickenRiceThunderTests() => ProviderSearchCache.Shared = new ProviderSearchCache();

    [Fact]
    public async Task TaggedThunderQueryPrioritizesFixedChickenRiceUploadAndKeepsOrdinaryUrlAsFallback()
    {
        var config = new PluginConfiguration();
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri =>
        {
            if (uri.Host == "api-shoulei-ssl.xunlei.com")
            {
                var query = Uri.UnescapeDataString(uri.Query);
                if (query.Contains("海南鸡字幕"))
                    return JsonSerializer.Serialize(new { code = 0, data = new[] { new { name = "ABC-123.海南鸡字幕.58.7KB.20261028.srt", url = "https://files.test/chicken.srt", ext = "srt", duration = 200000 } } });
                return JsonSerializer.Serialize(new { code = 0, data = new[] {
                    new { name = "ABC-123.srt", url = "https://files.test/ordinary.srt", ext = "srt", duration = 100000 },
                    new { name = "ABC-123 best timing.srt", url = "https://files.test/ordinary-best.srt", ext = "srt", duration = 100000 }
                } });
            }
            if (uri.AbsolutePath == "/ordinary-best.srt") return Srt("best timing subtitle", 100);
            if (uri.AbsolutePath == "/chicken.srt") return Srt("这是同一份已确认的中文字幕。", 200);
            if (uri.AbsolutePath == "/ordinary.srt") return Srt("这是同一份已确认的中文字幕。", 200);
            return Srt("ordinary subtitle", 100);
        });
        using var http = new PluginHttpClient(() => config, _ => handler);

        var results = (await new ThunderSubtitleProvider(http).Search(Request("abc-123-4k.mp4"), CancellationToken.None)).ToArray();

        Assert.Contains(handler.Calls, x => x.Host == "api-shoulei-ssl.xunlei.com" && Uri.UnescapeDataString(x.Query) == "?name=ABC-123");
        Assert.Contains(handler.Calls, x => x.Host == "api-shoulei-ssl.xunlei.com" && Uri.UnescapeDataString(x.Query).Contains("海南鸡字幕"));
        Assert.StartsWith("[海南鸡字幕] ABC-123.srt | 时长:", results[0].Name);
        Assert.DoesNotContain("58.7KB.20261028", results[0].Name);
        Assert.DoesNotContain("20261028", results[0].Name);
        Assert.Contains("大小:", results[0].Name);
        Assert.Contains("语言:", results[0].Name);
        var payload = ProviderSupport.Decode(results[0].Id);
        Assert.Equal("ABC-123.海南鸡字幕.58.7KB.20261028.srt", payload.Name);
        Assert.Equal("https://files.test/chicken.srt", payload.Url);
        Assert.Contains("https://files.test/ordinary.srt", payload.AlternateUrls);
        Assert.DoesNotContain("https://files.test/ordinary-best.srt", payload.AlternateUrls);
    }

    [Fact]
    public async Task FailedTaggedQueryDoesNotDiscardOrdinaryThunderResults()
    {
        var config = new PluginConfiguration { ThunderMaxResults = 10 };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri =>
        {
            if (uri.Host == "api-shoulei-ssl.xunlei.com")
            {
                if (Uri.UnescapeDataString(uri.Query).Contains("海南鸡字幕")) throw new HttpRequestException("synthetic tagged lookup failure");
                return JsonSerializer.Serialize(new { code = 0, data = new[] { new { name = "ABC-123.srt", url = "https://files.test/ordinary.srt", ext = "srt", duration = 100000 } } });
            }
            return Srt("ordinary subtitle", 100);
        });
        using var http = new PluginHttpClient(() => config, _ => handler);

        var results = (await new ThunderSubtitleProvider(http).Search(Request("ABC-123.mp4"), CancellationToken.None)).ToArray();

        Assert.Contains(handler.Calls, x => x.Host == "api-shoulei-ssl.xunlei.com" && Uri.UnescapeDataString(x.Query).Contains("海南鸡字幕"));
        Assert.Single(results);
        Assert.Contains("ABC-123.srt", results[0].Name);
        Assert.DoesNotContain("[海南鸡字幕]", results[0].Name);
    }

    [Fact]
    public async Task ChickenRicePriorityRequiresExactCodeLanguageAndSupportedSubtitleFormat()
    {
        var config = new PluginConfiguration { ThunderMaxResults = 10 };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri =>
        {
            if (uri.Host == "api-shoulei-ssl.xunlei.com")
            {
                if (Uri.UnescapeDataString(uri.Query).Contains("海南鸡字幕"))
                    return JsonSerializer.Serialize(new { code = 0, data = new[] {
                        new { name = "ABC-124.海南鸡字幕.58.7KB.20261028.srt", url = "https://files.test/wrong-code.srt", ext = "srt" },
                        new { name = "ABC-123.海南鸡字幕.58.7KB.20261028.srt", url = "https://files.test/wrong-format.srt", ext = "txt" },
                        new { name = "ABC-123.海南鸡字幕.srt", url = "https://files.test/not-fixed-name.srt", ext = "srt" }
                    } });
                return JsonSerializer.Serialize(new { code = 0, data = new[] {
                    new { name = "ABC-123.zh-CN.srt", url = "https://files.test/chinese.srt", ext = "srt" },
                    new { name = "ABC-123.jpn.srt", url = "https://files.test/japanese.srt", ext = "srt" },
                    new { name = "ABC-124.srt", url = "https://files.test/ordinary-wrong-code.srt", ext = "srt" }
                } });
            }
            return uri.AbsolutePath == "/japanese.srt" ? Srt("これは日本語の字幕です。", 100) :
                uri.AbsolutePath == "/not-fixed-name.srt" ? Srt("这是另一份中文字幕。", 50) : Srt("这是中文字幕。", 100);
        });
        using var http = new PluginHttpClient(() => config, _ => handler);

        var results = (await new ThunderSubtitleProvider(http).Search(Request("ABC-123.mp4"), CancellationToken.None)).ToArray();

        Assert.Equal(2, results.Length);
        Assert.Contains("ABC-123.zh-CN.srt", results[0].Name);
        Assert.Contains("ABC-123.海南鸡字幕.srt", results[1].Name);
        Assert.DoesNotContain(handler.Calls, x => x.AbsolutePath.Contains("wrong-code"));
        Assert.DoesNotContain(results, x => x.Name.Contains("wrong-format"));
    }

    [Fact]
    public async Task FixedChickenRiceFilenameWithoutConfirmedRequestedLanguageDoesNotGetPriority()
    {
        var config = new PluginConfiguration { ThunderMaxResults = 10 };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri =>
        {
            if (uri.Host == "api-shoulei-ssl.xunlei.com")
            {
                if (Uri.UnescapeDataString(uri.Query).Contains("海南鸡字幕"))
                    return JsonSerializer.Serialize(new { code = 0, data = new[] {
                        new { name = "ABC-123.海南鸡字幕.58.7KB.20261028.srt", url = "https://files.test/chicken-unknown-language.srt", ext = "srt", duration = 100000 }
                    } });
                return JsonSerializer.Serialize(new { code = 0, data = new[] {
                    new { name = "ABC-123.zh-CN.srt", url = "https://files.test/ordinary-chinese.srt", ext = "srt", duration = 100000 }
                } });
            }
            return uri.AbsolutePath.Contains("chicken-unknown-language")
                ? Srt("English subtitle without a language declaration.", 100)
                : Srt(string.Concat(Enumerable.Repeat("这是已确认的中文字幕。", 10)), 100);
        });
        using var http = new PluginHttpClient(() => config, _ => handler);

        var results = (await new ThunderSubtitleProvider(http).Search(Request("ABC-123.mp4"), CancellationToken.None)).ToArray();

        Assert.Equal(2, results.Length);
        Assert.Contains("ABC-123.zh-CN.srt", results[0].Name);
        Assert.StartsWith("[海南鸡字幕] ABC-123.srt | 时长:", results[1].Name);
        Assert.DoesNotContain("58.7KB.20261028", results[1].Name);
    }

    [Fact]
    public async Task ManualThunderSearchCapsCombinedCandidatesAtTenButAutomationSeesAll()
    {
        var config = new PluginConfiguration { ThunderMaxResults = 10 };
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var handler = new FixtureHandler(uri =>
        {
            if (uri.Host == "api-shoulei-ssl.xunlei.com")
            {
                if (Uri.UnescapeDataString(uri.Query).Contains("海南鸡字幕"))
                    return JsonSerializer.Serialize(new { code = 0, data = new[] { new { name = "ABC-123.海南鸡字幕.58.7KB.20261028.srt", url = "https://files.test/chicken.srt", ext = "srt", duration = 500000 } } });
                return JsonSerializer.Serialize(new { code = 0, data = Enumerable.Range(1, 12).Select(i => new
                    { name = $"ABC-123 第{i}版.srt", url = $"https://files.test/{i}.srt", ext = "srt", duration = 100000 }) });
            }
            var index = uri.AbsolutePath == "/chicken.srt" ? 99 : int.Parse(uri.AbsolutePath.Trim('/').Split('.')[0]);
            return uri.AbsolutePath == "/chicken.srt" ? Srt("这是已确认的海南鸡中文字幕。", 100) : Srt("ordinary subtitle " + index, 100);
        });
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = new ThunderSubtitleProvider(http);
        var request = Request("ABC-123.mp4");

        var manual = (await provider.Search(request, CancellationToken.None)).ToArray();
        using (SearchExecutionContext.BeginAutomation())
        {
            var automatic = (await provider.Search(request, CancellationToken.None)).ToArray();
            Assert.Equal(13, automatic.Length);
        }

        Assert.Equal(10, manual.Length);
        Assert.Contains("海南鸡字幕", manual[0].Name);
    }

    [Theory]
    [InlineData("abc-123-4k.mkv")]
    [InlineData("abc-123-无码破解.mkv")]
    [InlineData("abc-123-4k-无码破解.mkv")]
    public async Task VideoFilenameSuffixesKeepFullMediaPathAndSearchCanonicalCode(string filename)
    {
        var config = new PluginConfiguration();
        using var scope = Plugin.OverrideConfigurationForTests(config);
        var path = "/media/" + filename;
        var handler = new FixtureHandler(uri => uri.Host == "api-shoulei-ssl.xunlei.com"
            ? Uri.UnescapeDataString(uri.Query).Contains("海南鸡字幕")
                ? "{\"code\":0,\"data\":[]}"
                : JsonSerializer.Serialize(new { code = 0, data = new[] { new { name = "ABC-123.srt", url = "https://files.test/abc-123.srt", ext = "srt" } } })
            : Srt("这是中文字幕。", 100));
        using var http = new PluginHttpClient(() => config, _ => handler);

        var results = (await new ThunderSubtitleProvider(http).Search(Request(path), CancellationToken.None)).ToArray();

        var codeQueries = handler.Calls.Where(x => x.Host == "api-shoulei-ssl.xunlei.com").Select(x => Uri.UnescapeDataString(x.Query)).ToArray();
        Assert.Contains(codeQueries, x => x == "?name=ABC-123");
        Assert.Contains(codeQueries, x => x.Contains("海南鸡字幕 ABC-123"));
        var identifier = MediaIdentifier.TryParse(path);
        Assert.Equal("ABC-123", identifier.CanonicalCode);
        Assert.Equal(System.IO.Path.GetFileNameWithoutExtension(filename), identifier.OriginalStem);
        Assert.Equal(path, ProviderSupport.Decode(Assert.Single(results).Id).MediaPath);
    }

    private static MediaBrowser.Controller.Subtitles.SubtitleSearchRequest Request(string path) => new()
    {
        MediaPath = path, Language = "chi", RuntimeTicks = TimeSpan.FromSeconds(100).Ticks
    };

    private static string Srt(string text, int end) => $"1\n00:00:01,000 --> 00:{end / 60:00}:{end % 60:00},000\n{text}";

    private sealed class FixtureHandler : HttpMessageHandler
    {
        private readonly Func<Uri, string> _response;
        public ConcurrentQueue<Uri> Calls { get; } = new();
        public FixtureHandler(Func<Uri, string> response) => _response = response;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls.Enqueue(request.RequestUri);
            try { return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(_response(request.RequestUri), Encoding.UTF8) }); }
            catch (Exception error) { return Task.FromException<HttpResponseMessage>(error); }
        }
    }
}
