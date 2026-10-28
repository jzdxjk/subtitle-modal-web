using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
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
    public sealed class ThunderSubtitleProvider : ISubtitleProvider, IHasOrder
    {
        private readonly PluginHttpClient _http;
        private readonly ILogger _logger;
        private readonly SemaphoreSlim _prefetch = new SemaphoreSlim(4);
        private readonly SubtitleBodyCache _bodies = new SubtitleBodyCache();
        private readonly ConcurrentDictionary<string, CachedDocuments> _urls = new ConcurrentDictionary<string, CachedDocuments>(StringComparer.Ordinal);
        public ThunderSubtitleProvider(ILogManager logManager) : this(PluginHttpClient.Shared) { _logger = logManager?.GetLogger(GetType().Name); }
        internal ThunderSubtitleProvider(PluginHttpClient http) { _http = http; }
        public string Name => ProviderNames.Thunder;
        public int Order => ProviderOrder.Resolve(ProviderKeys.Thunder);
        public IEnumerable<VideoContentType> SupportedMediaTypes => new[] { VideoContentType.Movie, VideoContentType.Episode };
        public async Task<IEnumerable<RemoteSubtitleInfo>> Search(SubtitleSearchRequest request, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var identifier = MediaIdentifier.TryParse(request?.MediaPath);
            if (identifier == null) return Array.Empty<RemoteSubtitleInfo>();
            var config = Plugin.CurrentConfiguration;
            var key = ProviderSearchCache.Key(Name, request, Fingerprint(config));
            try
            {
                return await ProviderSearchCache.Shared.GetOrCreateAsync(key,
                    token => SearchCore(request, identifier, config, token), ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
            catch (Exception ex)
            {
                _logger?.Warn("Thunder subtitle search failed ({0}).", ex.GetType().Name);
                return Array.Empty<RemoteSubtitleInfo>();
            }
        }

        private static string Fingerprint(PluginConfiguration config) =>
            "max=" + config.ThunderMaxResults + ";timeout=" + config.ThunderTimeoutSeconds +
            ";proxy=" + (config.Proxy != null && config.Proxy.Enabled ? config.Proxy.Address : "");

        private async Task<IEnumerable<RemoteSubtitleInfo>> SearchCore(SubtitleSearchRequest request, MediaIdentifier identifier,
            PluginConfiguration config, CancellationToken ct)
        {
            // WhenAll preserves input order, so API response races do not choose duplicate metadata.
            var responses = await Task.WhenAll(identifier.QueryVariants.Select(x => Query(x, ct))).ConfigureAwait(false);
            // A cached empty result must mean the source answered; a total transport failure is retried next time.
            if (responses.Length != 0 && responses.All(x => x.Failed)) throw new IOException("Thunder subtitle search failed.");
            var rows = responses.SelectMany(x => x.Items ?? Array.Empty<ThunderItem>()).Where(x => x != null && ProviderSupport.HttpUrl(x.Url)
                && identifier.Matches(!string.IsNullOrWhiteSpace(x.Code) ? x.Code : (x.Name ?? "") + " " + (x.ExtraName ?? x.ExtraNameSnake ?? "")))
                .ToArray();
            var formats = rows.GroupBy(x => x.Url, StringComparer.Ordinal).Select(x => x.First()).ToArray();
            var downloads = await Task.WhenAll(formats.Select(x => Probe(x.Url, x.Ext, x.Name, ct))).ConfigureAwait(false);
            var byUrl = formats.Select((x, i) => new { x.Url, Documents = downloads[i] }).ToDictionary(x => x.Url, x => x.Documents, StringComparer.Ordinal);
            var candidates = new List<SubtitleCandidate>();
            foreach (var row in rows)
            {
                ct.ThrowIfCancellationRequested();
                var docs = byUrl[row.Url];
                var hintedLanguages = (row.Languages ?? Array.Empty<string>()).Select(SubtitleContent.NormalizeLanguage).Where(x => x != "unknown").ToArray();
                if (docs == null)
                {
                    var format = (row.Ext ?? "").TrimStart('.').ToLowerInvariant();
                    if (!SubtitleContent.IsSupported(format)) continue;
                    var language = hintedLanguages.FirstOrDefault(x => SubtitleContent.AcceptLanguage(request.Language, x)) ?? hintedLanguages.FirstOrDefault() ?? "unknown";
                    if (SubtitleContent.AcceptLanguage(request.Language, language)) candidates.Add(Candidate(row, request, null, language, candidates.Count));
                    continue;
                }
                foreach (var document in docs)
                {
                    var language = document.Language == "unknown" ? hintedLanguages.FirstOrDefault(x => SubtitleContent.AcceptLanguage(request.Language, x)) ?? hintedLanguages.FirstOrDefault() ?? "unknown" : document.Language;
                    if (!SubtitleContent.AcceptLanguage(request.Language, language)) continue;
                    if (MediaIdentifier.ContainsAnyCode(document.Name) && !identifier.Matches(document.Name)) continue;
                    candidates.Add(Candidate(row, request, document, language, candidates.Count));
                }
            }
            return ProviderSupport.Complete(ProviderSupport.Deduplicate(candidates), request, Name, config.ThunderMaxResults, "迅雷API");
        }

        private SubtitleCandidate Candidate(ThunderItem row, SubtitleSearchRequest request, SubtitleDocument document, string language, int index)
        {
            var payload = new DownloadPayload { Url = row.Url, Name = row.Name, Format = document?.Format ?? (row.Ext ?? "").TrimStart('.').ToLowerInvariant(), Language = request.Language,
                ContentHash = document?.ContentHash, EntryName = document?.Name, MediaPath = request.MediaPath };
            var timelineSeconds = document != null && document.DurationSeconds > 0 ? document.DurationSeconds : (double?)null;
            var apiSeconds = row.Duration > 0 ? row.Duration.Value / 1000d : (double?)null;
            var durationSeconds = timelineSeconds ?? apiSeconds;
            var durationSource = timelineSeconds.HasValue ? "字幕轴" : "迅雷API";
            return new SubtitleCandidate { Id = ProviderSupport.Encode(payload), Name = row.Name ?? document?.Name ?? "字幕", Format = payload.Format, Language = language,
                DurationSeconds = durationSeconds, DurationSource = durationSource, SizeBytes = document?.Bytes.LongLength,
                ContentHash = document?.ContentHash, DownloadUrl = row.Url, StableOrder = index };
        }

        private async Task<QueryOutcome> Query(string code, CancellationToken ct)
        {
            try
            {
                var bytes = await _http.GetBytesAsync("https://api-shoulei-ssl.xunlei.com/oracle/subtitle?name=" + Uri.EscapeDataString(code), NetworkPurpose.Thunder, ct, Plugin.CurrentConfiguration.ThunderTimeoutSeconds).ConfigureAwait(false);
                var response = ProviderSupport.Json<ThunderResponse>(bytes);
                return new QueryOutcome { Items = response.Code == 0 ? (IReadOnlyList<ThunderItem>)(response.Data ?? new List<ThunderItem>()) : Array.Empty<ThunderItem>() };
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
            catch (Exception ex) { _logger?.Warn("Thunder alias search failed ({0}).", ex.GetType().Name); return new QueryOutcome { Failed = true, Items = Array.Empty<ThunderItem>() }; }
        }

        private async Task<IReadOnlyList<SubtitleDocument>> Probe(string url, string format, string name, CancellationToken ct)
        {
            if (_urls.TryGetValue(url, out var cached) && cached.Expires > DateTimeOffset.UtcNow)
            {
                var documents = new List<SubtitleDocument>();
                foreach (var item in cached.Items)
                {
                    if (!_bodies.TryGet(item.ContentHash, out var bytes)) { documents.Clear(); break; }
                    documents.Add(new SubtitleDocument { Name = item.Name, Format = item.Format, Language = item.Language, DurationSeconds = item.DurationSeconds, ContentHash = item.ContentHash, Bytes = bytes });
                }
                if (documents.Count == cached.Items.Length) return documents;
            }
            await _prefetch.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                var bytes = await _http.GetBytesAsync(url, NetworkPurpose.Thunder, ct, Plugin.CurrentConfiguration.ThunderTimeoutSeconds).ConfigureAwait(false);
                var documents = SubtitleContent.ReadAll(bytes, format, name).ToArray();
                foreach (var doc in documents) _bodies.Put(doc.ContentHash, doc.Bytes);
                if (documents.Length != 0) _urls[url] = new CachedDocuments { Expires = DateTimeOffset.UtcNow.AddHours(24), Items = documents.Select(x => new CachedDocument { Name = x.Name, Format = x.Format, Language = x.Language, DurationSeconds = x.DurationSeconds, ContentHash = x.ContentHash }).ToArray() };
                foreach (var expired in _urls.Where(x => x.Value.Expires <= DateTimeOffset.UtcNow).Select(x => x.Key)) _urls.TryRemove(expired, out _);
                return documents;
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
            catch (Exception ex) { _logger?.Warn("Thunder subtitle prefetch failed ({0}).", ex.GetType().Name); return null; }
            finally { _prefetch.Release(); }
        }

        public async Task<SubtitleResponse> GetSubtitles(string id, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var payload = ProviderSupport.Decode(id);
            if (_bodies.TryGet(payload.ContentHash, out var cached))
                return ProviderSupport.Response(payload, new SubtitleDocument { Format = payload.Format, Bytes = cached });
            Exception failure = null;
            foreach (var url in new[] { payload.Url }.Concat(payload.AlternateUrls ?? Array.Empty<string>()).Distinct(StringComparer.Ordinal))
            {
                if (!ProviderSupport.HttpUrl(url)) continue;
                try
                {
                    var bytes = await _http.GetBytesAsync(url, NetworkPurpose.Thunder, ct, Plugin.CurrentConfiguration.ThunderTimeoutSeconds).ConfigureAwait(false);
                    var document = ProviderSupport.SelectDocument(bytes, payload);
                    _bodies.Put(document.ContentHash, document.Bytes);
                    return ProviderSupport.Response(payload, document);
                }
                catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
                catch (Exception ex) { failure = ex; }
            }
            throw new InvalidDataException("No valid subtitle download location remains.", failure);
        }

        private sealed class CachedDocuments { public DateTimeOffset Expires; public CachedDocument[] Items; }
        private sealed class CachedDocument { public string Name; public string Format; public string Language; public double? DurationSeconds; public string ContentHash; }
        private sealed class QueryOutcome { public IReadOnlyList<ThunderItem> Items; public bool Failed; }
        [DataContract] private sealed class ThunderResponse
        { [DataMember(Name = "code")] public int Code { get; set; } [DataMember(Name = "data")] public List<ThunderItem> Data { get; set; } }
        [DataContract] private sealed class ThunderItem
        {
            [DataMember(Name = "code")] public string Code { get; set; }
            [DataMember(Name = "url")] public string Url { get; set; }
            [DataMember(Name = "name")] public string Name { get; set; }
            [DataMember(Name = "extraname")] public string ExtraName { get; set; }
            [DataMember(Name = "extra_name")] public string ExtraNameSnake { get; set; }
            [DataMember(Name = "ext")] public string Ext { get; set; }
            [DataMember(Name = "duration")] public double? Duration { get; set; }
            [DataMember(Name = "languages")] public string[] Languages { get; set; }
            [DataMember(Name = "cid")] public string Cid { get; set; }
            [DataMember(Name = "gcid")] public string Gcid { get; set; }
        }
    }
}
