using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Model.Entities;
using MediaBrowser.Model.Providers;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class StaticPoolProviderTests
{
    private const string BuiltInPoolStaticUrl = "https://chickenrice-subtitle-static-00.jzdxjk.workers.dev";

    [Fact]
    public async Task BlankStaticPoolConfigurationRequestsTheBuiltInDirectory()
    {
        ProviderSearchCache.Shared = new ProviderSearchCache();
        var handler = new FixtureHandler(_ => new HttpResponseMessage(HttpStatusCode.NotFound));
        var config = new PluginConfiguration { PoolStaticUrl = "" };
        using var configuration = Plugin.OverrideConfigurationForTests(config);
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = CreateProvider(http);

        Assert.Empty(await provider.Search(Request("/media/ABP-192.mkv"), CancellationToken.None));
        Assert.NotEmpty(handler.Calls);
        Assert.Equal(
            BuiltInPoolStaticUrl + "/directory.json",
            handler.Calls[0].AbsoluteUri);
    }

    [Fact]
    public async Task StaticProviderUsesDirectoryAndCodeIndexThenVerifiesDownloadedSubtitle()
    {
        ProviderSearchCache.Shared = new ProviderSearchCache();
        const string code = "abp-192";
        const string body = "1\n00:00:01,000 --> 00:00:02,000\nSubtitle\n";
        var bytes = Encoding.UTF8.GetBytes(body);
        var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var shard = Bucket(code);
        var origin = "https://shard-" + shard + ".example";
        var directory = JsonSerializer.Serialize(new
        {
            version = 1,
            shard_count = 16,
            routing = "sha256-hex-first-nibble",
            shards = Enumerable.Range(0, 16).Select(id => new { id, origin = "https://shard-" + id + ".example" })
        });
        var index = JsonSerializer.Serialize(new
        {
            version = 1,
            canonical_code = code,
            display_code = "ABP-192",
            items = new[]
            {
                new
                {
                    canonical_code = code,
                    display_code = "ABP-192",
                    language = "zh",
                    format = "srt",
                    duration_seconds = 2,
                    size_bytes = bytes.Length,
                    sha256 = hash,
                    download_path = "/subtitles/" + hash + ".srt"
                }
            }
        });
        var handler = new FixtureHandler(uri =>
        {
            if (uri.AbsoluteUri == "https://bootstrap.example/directory.json") return Json(directory);
            if (uri.AbsoluteUri == origin + "/codes/" + code + ".json") return Json(index);
            if (uri.AbsoluteUri == origin + "/subtitles/" + hash + ".srt") return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) };
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });
        var config = new PluginConfiguration();
        SetPoolUrl(config, "https://bootstrap.example");
        using var configuration = Plugin.OverrideConfigurationForTests(config);
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = CreateProvider(http);

        var results = (await provider.Search(Request("/media/ABP-192.mkv"), CancellationToken.None)).ToArray();
        var result = Assert.Single(results);
        Assert.Equal("海南鸡字幕", result.ProviderName);
        Assert.Equal(new[]
        {
            "https://bootstrap.example/directory.json",
            origin + "/codes/" + code + ".json"
        }, handler.Calls.Take(2).Select(uri => uri.AbsoluteUri));

        var response = await provider.GetSubtitles(result.Id, CancellationToken.None);
        using var stream = response.Stream;
        using var actual = new System.IO.MemoryStream();
        await stream.CopyToAsync(actual);
        Assert.Equal(bytes, actual.ToArray());
        Assert.Equal(origin + "/subtitles/" + hash + ".srt", handler.Calls.Last().AbsoluteUri);
        Assert.DoesNotContain(handler.Calls, uri => uri.AbsolutePath.StartsWith("/api/v1/", StringComparison.Ordinal));
    }

    [Fact]
    public async Task StaticMissReturnsNoResultsWithoutCallingDynamicPoolApi()
    {
        ProviderSearchCache.Shared = new ProviderSearchCache();
        const string code = "abp-192";
        var origin = "https://shard-" + Bucket(code) + ".example";
        var directory = JsonSerializer.Serialize(new
        {
            version = 1,
            shard_count = 16,
            routing = "sha256-hex-first-nibble",
            shards = Enumerable.Range(0, 16).Select(id => new { id, origin = "https://shard-" + id + ".example" })
        });
        var handler = new FixtureHandler(uri => uri.AbsoluteUri == "https://bootstrap.example/directory.json"
            ? Json(directory)
            : new HttpResponseMessage(HttpStatusCode.NotFound));
        var config = new PluginConfiguration();
        SetPoolUrl(config, "https://bootstrap.example");
        using var configuration = Plugin.OverrideConfigurationForTests(config);
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = CreateProvider(http);

        Assert.Empty(await provider.Search(Request("/media/ABP-192.mkv"), CancellationToken.None));
        Assert.Equal(2, handler.Calls.Count);
        Assert.All(handler.Calls, uri => Assert.DoesNotContain("/api/v1/", uri.AbsolutePath));
        Assert.Equal(origin + "/codes/" + code + ".json", handler.Calls.Last().AbsoluteUri);
    }

    [Fact]
    public async Task SearchRejectsDownloadPathsOutsideTheContentAddressedSubtitleDirectory()
    {
        ProviderSearchCache.Shared = new ProviderSearchCache();
        const string code = "abp-192";
        const string body = "1\n00:00:01,000 --> 00:00:02,000\nSubtitle\n";
        var bytes = Encoding.UTF8.GetBytes(body);
        var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var origin = "https://shard-" + Bucket(code) + ".example";
        var directory = JsonSerializer.Serialize(new
        {
            version = 1,
            shard_count = 16,
            routing = "sha256-hex-first-nibble",
            shards = Enumerable.Range(0, 16).Select(id => new { id, origin = "https://shard-" + id + ".example" })
        });
        var index = JsonSerializer.Serialize(new
        {
            canonical_code = code,
            items = new[] { new
            {
                canonical_code = code,
                display_code = "ABP-192",
                language = "zh",
                format = "srt",
                duration_seconds = 2,
                size_bytes = bytes.Length,
                sha256 = hash,
                download_path = "/api/v1/subtitles/other-download"
            } }
        });
        var handler = new FixtureHandler(uri => uri.AbsoluteUri == "https://bootstrap.example/directory.json"
            ? Json(directory)
            : uri.AbsoluteUri == origin + "/codes/" + code + ".json"
                ? Json(index)
                : new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) });
        var config = new PluginConfiguration();
        SetPoolUrl(config, "https://bootstrap.example");
        using var configuration = Plugin.OverrideConfigurationForTests(config);
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = CreateProvider(http);

        Assert.Empty(await provider.Search(Request("/media/ABP-192.mkv"), CancellationToken.None));
        Assert.Equal(2, handler.Calls.Count);
        Assert.DoesNotContain(handler.Calls, uri => uri.AbsolutePath.StartsWith("/api/", StringComparison.Ordinal));
    }

    [Fact]
    public async Task StaticDirectoryRejectsTheLegacyDynamicWorkerAsAShardOrigin()
    {
        ProviderSearchCache.Shared = new ProviderSearchCache();
        var directory = JsonSerializer.Serialize(new
        {
            version = 1,
            shard_count = 16,
            routing = "sha256-hex-first-nibble",
            shards = Enumerable.Range(0, 16).Select(id => new
            {
                id,
                origin = id == 0 ? "https://chickenrice-subtitle-pool.jzdxjk.workers.dev" : "https://shard-" + id + ".example"
            })
        });
        var handler = new FixtureHandler(uri => Json(directory));
        var config = new PluginConfiguration();
        SetPoolUrl(config, "https://bootstrap.example");
        using var configuration = Plugin.OverrideConfigurationForTests(config);
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = CreateProvider(http);

        Assert.Empty(await provider.Search(Request("/media/ABP-192.mkv"), CancellationToken.None));
        Assert.Single(handler.Calls);
        Assert.Equal("/directory.json", handler.Calls[0].AbsolutePath);
    }

    [Fact]
    public async Task StaticDownloadRejectsBytesThatDoNotMatchTheIndexedSha256()
    {
        ProviderSearchCache.Shared = new ProviderSearchCache();
        const string code = "abp-192";
        const string expectedBody = "1\n00:00:01,000 --> 00:00:02,000\nSubtitle\n";
        const string returnedBody = "1\n00:00:01,000 --> 00:00:02,000\nChanged\n";
        var expectedBytes = Encoding.UTF8.GetBytes(expectedBody);
        var returnedBytes = Encoding.UTF8.GetBytes(returnedBody);
        var hash = Convert.ToHexString(SHA256.HashData(expectedBytes)).ToLowerInvariant();
        var origin = "https://shard-" + Bucket(code) + ".example";
        var directory = JsonSerializer.Serialize(new
        {
            version = 1, shard_count = 16, routing = "sha256-hex-first-nibble",
            shards = Enumerable.Range(0, 16).Select(id => new { id, origin = "https://shard-" + id + ".example" })
        });
        var index = JsonSerializer.Serialize(new
        {
            canonical_code = code,
            items = new[] { new { canonical_code = code, display_code = "ABP-192", language = "zh", format = "srt",
                duration_seconds = 2, size_bytes = expectedBytes.Length, sha256 = hash, download_path = "/subtitles/" + hash + ".srt" } }
        });
        var handler = new FixtureHandler(uri =>
        {
            if (uri.AbsoluteUri == "https://bootstrap.example/directory.json") return Json(directory);
            if (uri.AbsoluteUri == origin + "/codes/" + code + ".json") return Json(index);
            if (uri.AbsoluteUri == origin + "/subtitles/" + hash + ".srt")
                return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(returnedBytes) };
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });
        var config = new PluginConfiguration();
        SetPoolUrl(config, "https://bootstrap.example");
        using var configuration = Plugin.OverrideConfigurationForTests(config);
        using var http = new PluginHttpClient(() => config, _ => handler);
        var provider = CreateProvider(http);
        var candidate = Assert.Single(await provider.Search(Request("/media/ABP-192.mkv"), CancellationToken.None));

        await Assert.ThrowsAsync<System.IO.InvalidDataException>(() => provider.GetSubtitles(candidate.Id, CancellationToken.None));
    }

    private static int Bucket(string code)
        => int.Parse(SHA256.HashData(Encoding.UTF8.GetBytes(code))[0].ToString("x2").Substring(0, 1), System.Globalization.NumberStyles.HexNumber);

    private static HttpResponseMessage Json(string value)
        => new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(value, Encoding.UTF8, "application/json") };

    private static SubtitleSearchRequest Request(string path) => new SubtitleSearchRequest
    {
        MediaPath = path,
        Name = System.IO.Path.GetFileName(path),
        Language = "chi",
        RuntimeTicks = TimeSpan.FromSeconds(2).Ticks,
        ContentType = VideoContentType.Movie
    };

    private static void SetPoolUrl(PluginConfiguration configuration, string value)
    {
        var property = typeof(PluginConfiguration).GetProperty("PoolStaticUrl");
        Assert.NotNull(property);
        property.SetValue(configuration, value);
    }

    private static ISubtitleProvider CreateProvider(PluginHttpClient http)
    {
        var type = typeof(Plugin).Assembly.GetType("Emby.SubtitleAssistant.Providers.PoolSubtitleProvider");
        Assert.NotNull(type);
        var constructor = type.GetConstructor(BindingFlags.Instance | BindingFlags.NonPublic, null, new[] { typeof(PluginHttpClient) }, null);
        Assert.NotNull(constructor);
        return Assert.IsAssignableFrom<ISubtitleProvider>(constructor.Invoke(new object[] { http }));
    }

    private sealed class FixtureHandler : HttpMessageHandler
    {
        private readonly Func<Uri, HttpResponseMessage> _respond;
        public List<Uri> Calls { get; } = new List<Uri>();
        public FixtureHandler(Func<Uri, HttpResponseMessage> respond) => _respond = respond;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls.Add(request.RequestUri);
            return Task.FromResult(_respond(request.RequestUri));
        }
    }
}
