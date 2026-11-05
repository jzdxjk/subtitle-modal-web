using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Providers;

namespace Emby.SubtitleAssistant.Providers;

public sealed class PoolSubtitleProvider : ISubtitleProvider, IHasOrder
{
    private const int MaxIndexBytes = 4 * 1024 * 1024;
    private const int MaxSubtitleBytes = 16 * 1024 * 1024;
    private static readonly Regex HexHash = new Regex("^[a-f0-9]{64}$", RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly Regex SafeCode = new Regex("^[a-z0-9]+(?:-[a-z0-9]+)*$", RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private readonly PluginHttpClient _http;
    private readonly ILogger _logger;
    private readonly ProviderSearchCache _searches = new ProviderSearchCache(256, TimeSpan.Zero);
    private readonly SemaphoreSlim _directoryLock = new SemaphoreSlim(1, 1);
    private PoolDirectory _directory;
    private DateTimeOffset _directoryExpires;
    private string _directoryUrl;

    public PoolSubtitleProvider(ILogManager logManager) : this(PluginHttpClient.Shared)
        => _logger = logManager?.GetLogger(GetType().Name);

    internal PoolSubtitleProvider(PluginHttpClient http) => _http = http;

    public string Name => ProviderNames.Pool;
    public int Order => ProviderOrder.Resolve(ProviderKeys.Pool);
    public IEnumerable<VideoContentType> SupportedMediaTypes => new[] { VideoContentType.Movie, VideoContentType.Episode };

    public async Task<IEnumerable<RemoteSubtitleInfo>> Search(SubtitleSearchRequest request, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var identifier = MediaIdentifier.TryParse(request?.MediaPath);
        var config = Plugin.CurrentConfiguration;
        var baseUrl = (config.PoolStaticUrl ?? "").TrimEnd('/');
        if (identifier == null || !ProviderSupport.HttpUrl(baseUrl) || !baseUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            return Array.Empty<RemoteSubtitleInfo>();
        var key = ProviderSearchCache.Key(Name, request, "static=" + baseUrl + ";max=" + config.PoolMaxResults +
            ";timeout=" + config.PoolTimeoutSeconds + ";proxy=" + (config.Proxy != null && config.Proxy.Enabled ? config.Proxy.Address : ""));
        try
        {
            return await _searches.GetOrCreateAsync(key,
                token => SearchCore(request, identifier, config, baseUrl, token), ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
        catch (Exception ex)
        {
            _logger?.Warn("Static pool subtitle search failed ({0}).", ex.GetType().Name);
            return Array.Empty<RemoteSubtitleInfo>();
        }
    }

    private async Task<IEnumerable<RemoteSubtitleInfo>> SearchCore(SubtitleSearchRequest request, MediaIdentifier identifier,
        PluginConfiguration config, string baseUrl, CancellationToken ct)
    {
        var directory = await GetDirectory(baseUrl, config.PoolTimeoutSeconds, ct).ConfigureAwait(false);
        var code = (identifier.CanonicalCode ?? "").ToLowerInvariant();
        if (!SafeCode.IsMatch(code)) return Array.Empty<RemoteSubtitleInfo>();
        var bucket = Sha256(Encoding.UTF8.GetBytes(code))[0] >> 4;
        var origin = directory.Shards[bucket].Origin.TrimEnd('/');
        var indexUrl = origin + "/codes/" + Uri.EscapeDataString(code) + ".json";
        var bytes = await _http.GetBytesAsync(indexUrl, NetworkPurpose.Pool, ct, config.PoolTimeoutSeconds, MaxIndexBytes).ConfigureAwait(false);
        var index = ProviderSupport.Json<PoolCodeIndex>(bytes);
        if (index == null || !string.Equals(index.CanonicalCode, code, StringComparison.Ordinal) || index.Items == null)
            throw new InvalidDataException("Static pool code index is invalid.");

        var candidates = new List<SubtitleCandidate>();
        foreach (var item in index.Items)
        {
            ct.ThrowIfCancellationRequested();
            if (item == null || string.IsNullOrEmpty(item.CanonicalCode) || !identifier.Matches(item.CanonicalCode)) continue;
            var format = (item.Format ?? "").TrimStart('.').ToLowerInvariant();
            var language = SubtitleContent.NormalizeLanguage(item.Language);
            if (!SubtitleContent.IsSupported(format) || !SubtitleContent.AcceptLanguage(request.Language, language) ||
                item.SizeBytes <= 0 || item.SizeBytes > MaxSubtitleBytes || item.DurationSeconds <= 0 ||
                !HexHash.IsMatch(item.Sha256 ?? "")) continue;
            var hash = item.Sha256.ToLowerInvariant();
            var downloadUrl = ResolveAsset(origin, item.DownloadPath, hash, format);
            if (downloadUrl == null) continue;
            var displayCode = string.IsNullOrWhiteSpace(item.DisplayCode) ? item.CanonicalCode : item.DisplayCode;
            var name = displayCode + "." + format;
            var payload = new DownloadPayload
            {
                Url = downloadUrl, ContentHash = hash, Format = format, Language = request.Language,
                Name = name, MediaPath = request.MediaPath
            };
            candidates.Add(new SubtitleCandidate
            {
                Id = ProviderSupport.Encode(payload), Name = name, Format = format, Language = language,
                DurationSeconds = item.DurationSeconds, DurationSource = "字幕轴", SizeBytes = item.SizeBytes,
                ContentHash = hash, DownloadUrl = downloadUrl, StableOrder = candidates.Count
            });
        }
        return ProviderSupport.Complete(ProviderSupport.Deduplicate(candidates), request, Name, config.PoolMaxResults, "字幕轴");
    }

    private async Task<PoolDirectory> GetDirectory(string baseUrl, int timeout, CancellationToken ct)
    {
        if (_directory != null && _directoryUrl == baseUrl && _directoryExpires > DateTimeOffset.UtcNow) return _directory;
        await _directoryLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (_directory != null && _directoryUrl == baseUrl && _directoryExpires > DateTimeOffset.UtcNow) return _directory;
            var bytes = await _http.GetBytesAsync(baseUrl + "/directory.json", NetworkPurpose.Pool, ct, timeout, 262144).ConfigureAwait(false);
            var value = ProviderSupport.Json<PoolDirectory>(bytes);
            if (value?.Version != 1 || value.ShardCount != 16 || value.Routing != "sha256-hex-first-nibble" ||
                value.Shards == null || value.Shards.Length != 16) throw new InvalidDataException("Static pool directory is invalid.");
            var shards = new PoolShard[16];
            foreach (var shard in value.Shards)
            {
                if (shard == null || shard.Id < 0 || shard.Id > 15 || !ValidOrigin(shard.Origin) || shards[shard.Id] != null)
                    throw new InvalidDataException("Static pool directory is invalid.");
                shards[shard.Id] = new PoolShard { Id = shard.Id, Origin = shard.Origin.TrimEnd('/') };
            }
            if (shards.Any(x => x == null)) throw new InvalidDataException("Static pool directory is incomplete.");
            value.Shards = shards;
            _directoryUrl = baseUrl;
            _directory = value;
            _directoryExpires = DateTimeOffset.UtcNow.AddMinutes(5);
            return value;
        }
        finally { _directoryLock.Release(); }
    }

    public async Task<SubtitleResponse> GetSubtitles(string id, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var payload = ProviderSupport.Decode(id);
        if (!ProviderSupport.HttpUrl(payload.Url) || !payload.Url.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ||
            !SubtitleContent.IsSupported(payload.Format) || !HexHash.IsMatch(payload.ContentHash ?? ""))
            throw new InvalidDataException("Static pool subtitle reference is invalid.");
        var bytes = await _http.GetBytesAsync(payload.Url, NetworkPurpose.Pool, ct, Plugin.CurrentConfiguration.PoolTimeoutSeconds,
            MaxSubtitleBytes).ConfigureAwait(false);
        if (!string.Equals(Sha256Hex(bytes), payload.ContentHash, StringComparison.Ordinal))
            throw new InvalidDataException("Static pool subtitle SHA-256 verification failed.");
        return ProviderSupport.Response(payload, ProviderSupport.SelectDocument(bytes, payload));
    }

    private static string ResolveAsset(string origin, string path, string hash, string format)
    {
        if (!string.Equals(path, "/subtitles/" + hash + "." + format, StringComparison.Ordinal) ||
            string.IsNullOrEmpty(path) || path[0] != '/' || path.StartsWith("//", StringComparison.Ordinal) ||
            path.IndexOf('\\') >= 0 || path.IndexOf('?') >= 0 || path.IndexOf('#') >= 0 ||
            path.Split('/').Any(segment => segment == "." || segment == "..")) return null;
        if (!Uri.TryCreate(origin + path, UriKind.Absolute, out var uri) || !ValidOrigin(uri.GetLeftPart(UriPartial.Authority))) return null;
        return uri.AbsoluteUri;
    }

    private static bool ValidOrigin(string value)
    {
        return Uri.TryCreate(value, UriKind.Absolute, out var uri) && uri.Scheme == Uri.UriSchemeHttps &&
            !uri.Host.Equals("chickenrice-subtitle-pool.jzdxjk.workers.dev", StringComparison.OrdinalIgnoreCase) &&
            string.IsNullOrEmpty(uri.UserInfo) && uri.AbsolutePath == "/" && string.IsNullOrEmpty(uri.Query) &&
            string.IsNullOrEmpty(uri.Fragment);
    }

    private static byte[] Sha256(byte[] bytes) { using (var sha = SHA256.Create()) return sha.ComputeHash(bytes); }
    private static string Sha256Hex(byte[] bytes) => BitConverter.ToString(Sha256(bytes)).Replace("-", "").ToLowerInvariant();

    [DataContract]
    private sealed class PoolDirectory
    {
        [DataMember(Name = "version")] public int Version { get; set; }
        [DataMember(Name = "shard_count")] public int ShardCount { get; set; }
        [DataMember(Name = "routing")] public string Routing { get; set; }
        [DataMember(Name = "shards")] public PoolShard[] Shards { get; set; }
    }

    [DataContract]
    private sealed class PoolShard
    {
        [DataMember(Name = "id")] public int Id { get; set; }
        [DataMember(Name = "origin")] public string Origin { get; set; }
    }

    [DataContract]
    private sealed class PoolCodeIndex
    {
        [DataMember(Name = "canonical_code")] public string CanonicalCode { get; set; }
        [DataMember(Name = "items")] public PoolItem[] Items { get; set; }
    }

    [DataContract]
    private sealed class PoolItem
    {
        [DataMember(Name = "canonical_code")] public string CanonicalCode { get; set; }
        [DataMember(Name = "display_code")] public string DisplayCode { get; set; }
        [DataMember(Name = "language")] public string Language { get; set; }
        [DataMember(Name = "format")] public string Format { get; set; }
        [DataMember(Name = "duration_seconds")] public double DurationSeconds { get; set; }
        [DataMember(Name = "size_bytes")] public long SizeBytes { get; set; }
        [DataMember(Name = "sha256")] public string Sha256 { get; set; }
        [DataMember(Name = "download_path")] public string DownloadPath { get; set; }
    }
}
