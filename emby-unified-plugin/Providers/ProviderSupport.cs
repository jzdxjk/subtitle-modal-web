using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;
using System.Text;
using Emby.SubtitleAssistant.Core;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Model.Providers;

namespace Emby.SubtitleAssistant.Providers
{
    internal static class ProviderSupport
    {
        // Search IDs expire with this process; the key is never persisted or logged.
        private static readonly byte[] SigningKey = NewSigningKey();
        private static byte[] NewSigningKey() { var key = new byte[32]; using (var random = RandomNumberGenerator.Create()) random.GetBytes(key); return key; }
        private static string Base64Url(byte[] value) => Convert.ToBase64String(value).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        private static byte[] Unbase64Url(string value)
        {
            value = value.Replace('-', '+').Replace('_', '/');
            return Convert.FromBase64String(value + new string('=', (4 - value.Length % 4) % 4));
        }
        private static byte[] Signature(string value) { using (var hmac = new HMACSHA256(SigningKey)) return hmac.ComputeHash(Encoding.ASCII.GetBytes(value)); }
        public static T Json<T>(byte[] bytes)
        { using (var input = new MemoryStream(bytes)) return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(input); }
        public static string Encode(DownloadPayload payload)
        {
            using (var stream = new MemoryStream())
            {
                new DataContractJsonSerializer(typeof(DownloadPayload)).WriteObject(stream, payload);
                var value = Base64Url(stream.ToArray());
                return "sa1." + value + "." + Base64Url(Signature(value));
            }
        }
        public static DownloadPayload Decode(string id)
        {
            try
            {
                var marker = (id ?? "").IndexOf("sa1.", StringComparison.Ordinal);
                if (marker < 0) throw new InvalidDataException("Invalid subtitle download identifier.");
                var parts = id.Substring(marker + 4).Split('.');
                if (parts.Length != 2) throw new InvalidDataException("Invalid subtitle download identifier.");
                var expected = Signature(parts[0]);
                var actual = Unbase64Url(parts[1]);
                var difference = expected.Length ^ actual.Length;
                for (var i = 0; i < expected.Length; i++) difference |= expected[i] ^ (i < actual.Length ? actual[i] : 0);
                if (difference != 0) throw new InvalidDataException("Invalid subtitle download identifier.");
                return Json<DownloadPayload>(Unbase64Url(parts[0]));
            }
            catch (FormatException ex) { throw new InvalidDataException("Invalid subtitle download identifier.", ex); }
        }
        public static IEnumerable<RemoteSubtitleInfo> Complete(IEnumerable<SubtitleCandidate> candidates, SubtitleSearchRequest request, string provider, int maxResults, string durationSource)
        {
            var runtime = request.RuntimeTicks > 0 ? request.RuntimeTicks.Value / (double)TimeSpan.TicksPerSecond : (double?)null;
            var ordered = SubtitleRanking.Order(candidates, runtime).AsEnumerable();
            if (!SearchExecutionContext.IsAutomation) ordered = ordered.Take(Math.Max(1, maxResults));
            return ordered.Select(x => new RemoteSubtitleInfo
            {
                Id = x.Id, Name = x.Name + " | 时长:" + Duration(x.DurationSeconds) + "(" + durationSource + ") | 大小:" + Size(x.SizeBytes) + " | 语言:" + LanguageName(x.Language),
                Language = request.Language, ProviderName = provider, Format = x.Format, Author = "字幕助手",
                Comment = "Code matching: exact | SHA256: " + (x.ContentHash ?? "unknown") + " | Language: " + (x.Language ?? "unknown"),
                IsHashMatch = false, IsForced = false
            }).ToArray();
        }
        public static string LanguageName(string language) => language == "chi" ? "中文" : language == "eng" ? "英语" : language == "jpn" ? "日语" : language == "tha" ? "泰语" : language == "kor" ? "韩语" : "未知";
        private static string Duration(double? seconds) => seconds > 0 ? TimeSpan.FromSeconds(seconds.Value).ToString(@"hh\:mm\:ss", CultureInfo.InvariantCulture) : "unknown";
        private static string Size(long? size) => size.HasValue ? size.Value.ToString(CultureInfo.InvariantCulture) + " B" : "unknown";
        public static bool HttpUrl(string value) => Uri.TryCreate(value, UriKind.Absolute, out var uri) && (uri.Scheme == "http" || uri.Scheme == "https") && string.IsNullOrEmpty(uri.UserInfo);
        public static SubtitleResponse Response(DownloadPayload payload, SubtitleDocument document)
            => new SubtitleResponse { Language = payload.Language, IsForced = payload.IsForced, Format = document.Format,
                Stream = Automation.DownloadWriteObserver.Wrap(new MemoryStream(document.Bytes, false), payload.MediaPath) };
        public static SubtitleDocument SelectDocument(byte[] bytes, DownloadPayload payload)
        {
            var docs = SubtitleContent.ReadAll(bytes, payload.Format, payload.EntryName ?? payload.Name);
            var doc = docs.FirstOrDefault(x => !string.IsNullOrEmpty(payload.ContentHash) ? x.ContentHash == payload.ContentHash : string.IsNullOrEmpty(payload.EntryName) || x.Name == payload.EntryName);
            if (doc == null) throw new InvalidDataException("Subtitle content is invalid or has changed since search.");
            return doc;
        }
        public static IEnumerable<SubtitleCandidate> Deduplicate(IEnumerable<SubtitleCandidate> source)
        {
            var seen = new Dictionary<string, SubtitleCandidate>(StringComparer.Ordinal);
            var result = new List<SubtitleCandidate>();
            foreach (var item in source)
            {
                var key = (item.ContentHash ?? "url:" + item.DownloadUrl) + "|" + item.Format + "|" + item.Language;
                if (!seen.TryGetValue(key, out var first)) { seen[key] = item; result.Add(item); continue; }
                var payload = Decode(first.Id);
                var duplicate = Decode(item.Id);
                payload.AlternateUrls = new[] { payload.Url }.Concat(payload.AlternateUrls ?? Array.Empty<string>()).Concat(new[] { duplicate.Url }).Concat(duplicate.AlternateUrls ?? Array.Empty<string>()).Where(x => !string.IsNullOrEmpty(x)).Distinct(StringComparer.Ordinal).ToArray();
                payload.AlternatePaths = new[] { payload.Path }.Concat(payload.AlternatePaths ?? Array.Empty<string>()).Concat(new[] { duplicate.Path }).Concat(duplicate.AlternatePaths ?? Array.Empty<string>()).Where(x => !string.IsNullOrEmpty(x)).Distinct(StringComparer.Ordinal).ToArray();
                first.Id = Encode(payload);
            }
            return result;
        }
    }

    [DataContract]
    internal sealed class DownloadPayload
    {
        [DataMember] public string Url { get; set; }
        [DataMember] public string Path { get; set; }
        [DataMember] public string ContentHash { get; set; }
        [DataMember] public string EntryName { get; set; }
        [DataMember] public string Format { get; set; }
        [DataMember] public string Language { get; set; }
        [DataMember] public string Name { get; set; }
        [DataMember] public string MediaPath { get; set; }
        [DataMember] public string PoolId { get; set; }
        [DataMember] public string[] AlternateUrls { get; set; }
        [DataMember] public string[] AlternatePaths { get; set; }
        [DataMember] public bool IsForced { get; set; }
    }
}
