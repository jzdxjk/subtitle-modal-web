using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace Emby.SubtitleAssistant.Core
{
    public sealed class SubtitleDocument
    {
        public string Name { get; set; }
        public string Format { get; set; }
        public byte[] Bytes { get; set; }
        public double? DurationSeconds { get; set; }
        public string Language { get; set; }
        public string ContentHash { get; set; }
    }

    public static class SubtitleContent
    {
        public static IReadOnlyList<SubtitleDocument> ReadAll(byte[] bytes, string format, string name)
            => ReadAll(bytes, format, name, true);
        private static IReadOnlyList<SubtitleDocument> ReadAll(byte[] bytes, string format, string name, bool allowArchive)
        {
            if (bytes == null || bytes.Length == 0) return Array.Empty<SubtitleDocument>();
            if (bytes.Length > 3 && bytes[0] == 'P' && bytes[1] == 'K')
            {
                if (!allowArchive) return Array.Empty<SubtitleDocument>();
                var results = new List<SubtitleDocument>();
                try
                {
                    using (var zip = new ZipArchive(new MemoryStream(bytes), ZipArchiveMode.Read))
                    {
                        long expanded = 0;
                        foreach (var entry in zip.Entries)
                        {
                            var ext = Path.GetExtension(entry.Name).TrimStart('.').ToLowerInvariant();
                            if (!IsSupported(ext) || entry.Length > 16777216) continue;
                            expanded += entry.Length;
                            if (expanded > 67108864) break;
                            using (var stream = entry.Open())
                            using (var output = new MemoryStream())
                            { stream.CopyTo(output); results.AddRange(ReadAll(output.ToArray(), ext, entry.Name, false)); }
                        }
                    }
                }
                catch (InvalidDataException) { }
                return results;
            }
            format = (format ?? "").TrimStart('.').ToLowerInvariant();
            if (!IsSupported(format)) return Array.Empty<SubtitleDocument>();
            var text = Decode(bytes).TrimStart('\uFEFF', ' ', '\t', '\r', '\n');
            if (text.StartsWith("<", StringComparison.Ordinal) || text.StartsWith("{", StringComparison.Ordinal)) return Array.Empty<SubtitleDocument>();
            var duration = MaximumEnd(text, format);
            if (!duration.HasValue) return Array.Empty<SubtitleDocument>();
            var hint = Regex.Match(Path.GetFileNameWithoutExtension(name ?? ""), @"(?:^|[._ -])(?<language>chi|zho|zh(?:[-_](?:cn|tw|hk|hans|hant))?|eng|en|jpn|ja|tha|th|kor|ko)(?:[._ -](?:forced|default|sdh|cc))*$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
            var language = hint.Success ? NormalizeLanguage(hint.Groups["language"].Value) : DetectLanguage(DialogueText(text, format));
            return new[] { new SubtitleDocument { Name = name, Format = format, Bytes = bytes, DurationSeconds = duration, Language = language, ContentHash = Hash(bytes) } };
        }

        public static bool IsSupported(string format) => format == "srt" || format == "ass" || format == "ssa";
        public static string Hash(byte[] bytes)
        { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }

        public static string Decode(byte[] bytes)
        {
            if (bytes.Length > 1 && ((bytes[0] == 0xFF && bytes[1] == 0xFE) || (bytes[0] == 0xFE && bytes[1] == 0xFF)))
                using (var reader = new StreamReader(new MemoryStream(bytes), Encoding.UTF8, true)) return reader.ReadToEnd();
            try { return new UTF8Encoding(false, true).GetString(bytes); }
            catch (DecoderFallbackException)
            {
                try
                {
                    var providerType = Type.GetType("System.Text.CodePagesEncodingProvider, System.Text.Encoding.CodePages", false);
                    if (providerType?.GetProperty("Instance")?.GetValue(null) is EncodingProvider provider) Encoding.RegisterProvider(provider);
                    return Encoding.GetEncoding("GB18030").GetString(bytes);
                }
                catch (ArgumentException) { return Encoding.UTF8.GetString(bytes); }
                catch (NotSupportedException) { return Encoding.UTF8.GetString(bytes); }
            }
        }

        private static double? MaximumEnd(string text, string format)
        {
            var ends = new List<double>();
            if (format == "srt")
            {
                foreach (Match match in Regex.Matches(text, @"\d{1,3}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*(?<end>\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})"))
                    if (Time(match.Groups["end"].Value, out var end)) ends.Add(end);
            }
            else
            {
                var endIndex = 2;
                foreach (var line in text.Split('\n'))
                {
                    var trimmed = line.Trim();
                    if (trimmed.StartsWith("Format:", StringComparison.OrdinalIgnoreCase))
                    {
                        var fields = trimmed.Substring(7).Split(',').Select(x => x.Trim()).ToArray();
                        var index = Array.FindIndex(fields, x => x.Equals("End", StringComparison.OrdinalIgnoreCase));
                        if (index >= 0) endIndex = index;
                    }
                    if (!trimmed.StartsWith("Dialogue:", StringComparison.OrdinalIgnoreCase)) continue;
                    var values = trimmed.Substring(9).Split(',');
                    if (values.Length > endIndex && Time(values[endIndex], out var end)) ends.Add(end);
                }
            }
            return ends.Count == 0 ? (double?)null : ends.Max();
        }

        private static bool Time(string value, out double seconds)
        {
            seconds = 0;
            var parts = value.Trim().Replace(',', '.').Split(':');
            if (parts.Length != 3 || !int.TryParse(parts[0], out var h) || !int.TryParse(parts[1], out var m)
                || !double.TryParse(parts[2], NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var s) || m < 0 || m >= 60 || s < 0 || s >= 60) return false;
            seconds = h * 3600d + m * 60d + s;
            return true;
        }

        public static string NormalizeLanguage(string value)
        {
            value = (value ?? "").Trim().Replace('_', '-').ToLowerInvariant();
            if (value == "chi" || value == "zho" || value == "zh" || value.StartsWith("zh-") || value.Contains("简体") || value.Contains("繁体") || value.Contains("中文") || value.Contains("chinese")) return "chi";
            if (value == "en" || value == "eng" || value.Contains("english") || value.Contains("英语")) return "eng";
            if (value == "ja" || value == "jpn" || value.Contains("日语")) return "jpn";
            if (value == "th" || value == "tha" || value.Contains("thai")) return "tha";
            if (value == "ko" || value == "kor") return "kor";
            return "unknown";
        }
        public static bool AcceptLanguage(string requested, string actual)
            => actual == "unknown" || NormalizeLanguage(requested) == "unknown" || NormalizeLanguage(requested) == actual;
        private static string DetectLanguage(string text)
        {
            var counts = CountScripts(text);
            // A separate Chinese translation sentence is evidence of bilingual content.
            if (counts.Han >= 4 && text.Split(new[] { '\r', '\n', '。', '！', '？', '/', '|' }).Any(x => { var line = CountScripts(x); return line.Han >= 4 && line.Foreign == 0; })) return "chi";
            var total = counts.Han + counts.Foreign;
            if (counts.Han > 0 && counts.Foreign <= total * 0.20) return "chi";
            var dominant = Math.Max(counts.Kana, Math.Max(counts.Thai, counts.Hangul));
            if (dominant >= 4 && dominant >= total * 0.20)
                return dominant == counts.Kana ? "jpn" : dominant == counts.Thai ? "tha" : "kor";
            return "unknown";
        }

        private static string DialogueText(string text, string format)
        {
            var dialogue = new StringBuilder();
            var textIndex = 9;
            foreach (var raw in text.Split('\n'))
            {
                var line = raw.Trim();
                if (format == "srt")
                {
                    if (Regex.IsMatch(line, @"^\d+$|^\d{1,3}:\d{2}:\d{2}.*-->")) continue;
                    dialogue.AppendLine(line);
                    continue;
                }
                if (line.StartsWith("Format:", StringComparison.OrdinalIgnoreCase))
                {
                    var fields = line.Substring(7).Split(',');
                    var index = Array.FindIndex(fields, x => x.Trim().Equals("Text", StringComparison.OrdinalIgnoreCase));
                    if (index >= 0) textIndex = index;
                }
                if (!line.StartsWith("Dialogue:", StringComparison.OrdinalIgnoreCase)) continue;
                var columns = line.Substring(9).Split(new[] { ',' }, textIndex + 1);
                if (columns.Length > textIndex) dialogue.AppendLine(columns[textIndex]);
            }
            var plain = Regex.Replace(dialogue.ToString(), @"\{[^}]*\}", "");
            plain = Regex.Replace(plain, @"<br\s*/?>", "\n", RegexOptions.IgnoreCase);
            plain = Regex.Replace(plain, @"<[^>]*>", "");
            return plain.Replace(@"\N", "\n").Replace(@"\n", "\n").Replace(@"\h", " ");
        }

        private static ScriptCounts CountScripts(string text)
        {
            var result = new ScriptCounts();
            foreach (var ch in text)
            {
                if ((ch >= '\u3400' && ch <= '\u4DBF') || (ch >= '\u4E00' && ch <= '\u9FFF') || (ch >= '\uF900' && ch <= '\uFAFF')) result.Han++;
                else if (ch >= '\u3040' && ch <= '\u30FF') result.Kana++;
                else if (ch >= '\u0E00' && ch <= '\u0E7F') result.Thai++;
                else if (ch >= '\uAC00' && ch <= '\uD7AF') result.Hangul++;
            }
            return result;
        }
        private struct ScriptCounts { public int Han, Kana, Thai, Hangul; public int Foreign => Kana + Thai + Hangul; }
    }
}
