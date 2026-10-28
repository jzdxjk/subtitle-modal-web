using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Providers;
namespace Emby.SubtitleAssistant.Providers
{
    public sealed class PoolSubtitleProvider : ISubtitleProvider, IHasOrder
    {
        private readonly PluginHttpClient _http;
        private readonly ILogger _logger;
        public PoolSubtitleProvider(ILogManager logManager) : this(PluginHttpClient.Shared) { _logger = logManager?.GetLogger(GetType().Name); }
        internal PoolSubtitleProvider(PluginHttpClient http) { _http = http; }
        public string Name => ProviderNames.Pool;
        public int Order => ProviderOrder.Resolve(ProviderKeys.Pool);
        public IEnumerable<VideoContentType> SupportedMediaTypes => new[] { VideoContentType.Movie, VideoContentType.Episode };
        public async Task<IEnumerable<RemoteSubtitleInfo>> Search(SubtitleSearchRequest request, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var identifier = MediaIdentifier.TryParse(request?.MediaPath);
            var config = Plugin.CurrentConfiguration;
            var baseUrl = (config.PoolUrl ?? "").TrimEnd('/');
            if (identifier == null || !ProviderSupport.HttpUrl(baseUrl)) return Array.Empty<RemoteSubtitleInfo>();
            var key = ProviderSearchCache.Key(Name, request, "url=" + baseUrl + ";max=" + config.PoolMaxResults +
                ";timeout=" + config.PoolTimeoutSeconds + ";proxy=" + (config.Proxy != null && config.Proxy.Enabled ? config.Proxy.Address : ""));
            try
            {
                return await ProviderSearchCache.Shared.GetOrCreateAsync(key,
                    token => SearchCore(request, identifier, config, baseUrl, token), ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
            catch (Exception ex) { _logger?.Warn("Pool subtitle search failed ({0}).", ex.GetType().Name); return Array.Empty<RemoteSubtitleInfo>(); }
        }
        private async Task<IEnumerable<RemoteSubtitleInfo>> SearchCore(SubtitleSearchRequest request, MediaIdentifier identifier,
            PluginConfiguration config, string baseUrl, CancellationToken ct)
        {
            var url = baseUrl + "/api/v1/subtitles/search?match=work&" + string.Join("&", identifier.QueryVariants.Select(x => "codes=" + Uri.EscapeDataString(x)));
            var response = ProviderSupport.Json<PoolResponse>(await _http.GetBytesAsync(url, NetworkPurpose.Pool, ct, config.PoolTimeoutSeconds).ConfigureAwait(false));
            var candidates = new List<SubtitleCandidate>();
            foreach (var item in response.Items ?? new List<PoolItem>())
            {
                if (string.IsNullOrWhiteSpace(item.Id) || !identifier.Matches(item.Code)) continue;
                var format = (item.Format ?? "").ToLowerInvariant().TrimStart('.');
                if (!SubtitleContent.IsSupported(format)) continue;
                var language = SubtitleContent.NormalizeLanguage(item.Language);
                if (!SubtitleContent.AcceptLanguage(request.Language, language)) continue;
                var payload = new DownloadPayload { PoolId = item.Id, Format = format, Language = request.Language, ContentHash = string.IsNullOrWhiteSpace(item.Sha256) ? null : item.Sha256.ToLowerInvariant(), Name = item.Code + "." + format, MediaPath = request.MediaPath };
                candidates.Add(new SubtitleCandidate { Id = ProviderSupport.Encode(payload), Name = payload.Name, Format = format, Language = language, DurationSeconds = item.DurationSeconds > 0 ? item.DurationSeconds : null, SizeBytes = item.SizeBytes >= 0 ? item.SizeBytes : null, ContentHash = payload.ContentHash, DownloadUrl = baseUrl + "/" + item.Id, StableOrder = candidates.Count });
            }
            return ProviderSupport.Complete(ProviderSupport.Deduplicate(candidates), request, Name, config.PoolMaxResults, "字幕轴");
        }
        public async Task<SubtitleResponse> GetSubtitles(string id, CancellationToken ct)
        {
            var payload = ProviderSupport.Decode(id);
            if (string.IsNullOrWhiteSpace(payload.PoolId)) throw new InvalidDataException("Missing pool subtitle ID.");
            var config = Plugin.CurrentConfiguration;
            var baseUrl = (config.PoolUrl ?? "").TrimEnd('/');
            if (!ProviderSupport.HttpUrl(baseUrl)) throw new InvalidDataException("Pool URL is not configured.");
            var bytes = await _http.GetBytesAsync(baseUrl + "/api/v1/subtitles/" + Uri.EscapeDataString(payload.PoolId) + "/download", NetworkPurpose.Pool, ct, config.PoolTimeoutSeconds).ConfigureAwait(false);
            return ProviderSupport.Response(payload, ProviderSupport.SelectDocument(bytes, payload));
        }
        [DataContract] private sealed class PoolResponse { [DataMember(Name = "items")] public List<PoolItem> Items { get; set; } }
        [DataContract] private sealed class PoolItem
        {
            [DataMember(Name = "id")] public string Id { get; set; }
            [DataMember(Name = "code")] public string Code { get; set; }
            [DataMember(Name = "format")] public string Format { get; set; }
            [DataMember(Name = "duration_seconds")] public double? DurationSeconds { get; set; }
            [DataMember(Name = "size_bytes")] public long? SizeBytes { get; set; }
            [DataMember(Name = "sha256")] public string Sha256 { get; set; }
            [DataMember(Name = "language")] public string Language { get; set; }
        }
    }
}
