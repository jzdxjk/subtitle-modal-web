using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization.Json;
using System.Text.RegularExpressions;
namespace Emby.SubtitleAssistant.Core
{
    public sealed class MediaIdentifier
    {
        private static readonly RegexOptions Options = RegexOptions.IgnoreCase | RegexOptions.CultureInvariant;
        private static readonly IReadOnlyDictionary<string, string> AmateurPrefixes = LoadPrefixes();
        private string Identity { get; set; }
        private string[] EquivalentIdentities { get; set; }
        public string CanonicalCode { get; private set; }
        public string OriginalStem { get; private set; }
        public IReadOnlyList<string> QueryVariants { get; private set; }
        public static MediaIdentifier TryParse(string mediaPath)
        {
            if (string.IsNullOrWhiteSpace(mediaPath)) return null;
            var filename = mediaPath.Replace('\\', '/').Split('/').Last();
            var stem = Path.GetFileNameWithoutExtension(filename);
            var found = ParseText(stem);
            if (found.Count != 1) return null;
            var result = found[0];
            result.OriginalStem = stem;
            return result;
        }

        public bool Matches(string text)
        {
            var found = ParseText(text, true);
            return found.Count == 1 && Accepts(found[0]);
        }
        private bool Accepts(MediaIdentifier other) => EquivalentIdentities.Contains(other.Identity, StringComparer.Ordinal);
        internal static bool ContainsAnyCode(string text) => ParseText(text, true).Count != 0;

        private static List<MediaIdentifier> ParseText(string text, bool candidate = false)
        {
            text = Regex.Replace(text ?? string.Empty, @"(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|tv|cc|xyz|me|club)(?::\d+)?@?", " ", Options);
            text = Regex.Replace(text, @"(?<![A-Z0-9])(?:CD|PART|DISC)[-_ ]?\d{1,2}(?![A-Z0-9])", " ", Options);
            var spans = new List<Tuple<int, int>>();
            var results = new List<MediaIdentifier>();
            void Collect(string pattern, Func<Match, MediaIdentifier> create)
            {
                foreach (Match match in Regex.Matches(text, pattern, Options))
                {
                    if (spans.Any(x => match.Index < x.Item2 && match.Index + match.Length > x.Item1)) continue;
                    spans.Add(Tuple.Create(match.Index, match.Index + match.Length));
                    var value = create(match);
                    if (value == null) continue;
                    var equivalent = results.FindIndex(x => x.Accepts(value) || value.Accepts(x));
                    if (equivalent < 0) results.Add(value);
                    else if (value.QueryVariants.Count > results[equivalent].QueryVariants.Count) results[equivalent] = value;
                }
            }
            Collect(@"(?<![A-Z0-9])FC2[-_ ]?(?:PPV[-_ ]?)?(?<num>\d{3,12})(?![A-Z0-9])", m =>
            {
                var n = m.Groups["num"].Value;
                return Create("FC2:" + NumberIdentity(n), "FC2-PPV-" + n, "FC2-PPV-" + n, "FC2PPV-" + n, "FC2-" + n);
            });
            Collect(@"(?<![A-Z0-9])(?<date>\d{6})[-_](?<num>\d{2,5})(?![A-Z0-9])", m =>
            {
                var d = m.Groups["date"].Value;
                var n = m.Groups["num"].Value;
                return Create("DATE:" + d + ":" + n, d + "-" + n, d + "-" + n, d + "_" + n);
            });
            var namedWidth = candidate ? 8 : 6;
            Collect($@"(?<![A-Z0-9])HEYZO[-_ ]?(?<num>\d{{3,{namedWidth}}})(?![A-Z0-9])", m =>
            {
                var n = m.Groups["num"].Value;
                return Create("HEYZO:" + NumberIdentity(n), "HEYZO-" + n, "HEYZO-" + n, "HEYZO_" + n, "HEYZO" + n);
            });
            Collect($@"(?<![A-Z0-9])N[-_ ]?(?<num>\d{{3,{namedWidth}}})(?![A-Z0-9])", m =>
            {
                var n = m.Groups["num"].Value;
                return Create("N:" + NumberIdentity(n), "N" + n, "N-" + n, "N_" + n, "N" + n);
            });
            var ordinaryWidth = candidate ? 8 : 7;
            Collect($@"(?<![A-Z0-9])(?<prefix>(?:\d{{2,4}})?[A-Z]{{2,10}})[-_ ]?(?<num>\d{{1,{ordinaryWidth}}})(?![A-Z0-9])", FromOrdinaryMatch);
            Collect($@"(?<![A-Z0-9])(?<prefix>[A-Z][A-Z0-9]{{1,9}})[-_](?<num>\d{{1,{ordinaryWidth}}})(?![A-Z0-9])", FromOrdinaryMatch);
            return results;
        }

        private static MediaIdentifier FromOrdinaryMatch(Match match)
        {
            var prefix = match.Groups["prefix"].Value.ToUpperInvariant();
            if (new[] { "CD", "PART", "DISC", "H", "X", "MP", "UTF", "HDD", "HHD" }.Contains(prefix)) return null;
            var number = match.Groups["num"].Value;
            var shortPrefix = AmateurPrefixes.FirstOrDefault(x => x.Value == prefix).Key;
            if (AmateurPrefixes.TryGetValue(prefix, out var fullPrefix)) shortPrefix = prefix;
            else fullPrefix = shortPrefix == null ? prefix : AmateurPrefixes[shortPrefix];
            var unknownNumericPrefix = false;
            if (shortPrefix == null)
            {
                var numericPrefix = Regex.Match(prefix, @"^\d+(?<short>[A-Z]+)$");
                if (numericPrefix.Success && !AmateurPrefixes.ContainsKey(numericPrefix.Groups["short"].Value))
                { shortPrefix = numericPrefix.Groups["short"].Value; unknownNumericPrefix = true; }
            }
            var prefixes = shortPrefix == null ? new[] { prefix } : new[] { fullPrefix, shortPrefix };
            var variants = prefixes.Select(p => p + "-" + number).ToArray();
            var result = Create(fullPrefix + ":" + NumberIdentity(number), fullPrefix + "-" + number, variants);
            if (unknownNumericPrefix) result.EquivalentIdentities = new[] { result.Identity, shortPrefix + ":" + NumberIdentity(number) };
            return result;
        }

        private static string NumberIdentity(string value) => value.TrimStart('0').Length == 0 ? "0" : value.TrimStart('0');
        private static MediaIdentifier Create(string identity, string canonical, params string[] variants)
            => new MediaIdentifier { Identity = identity, EquivalentIdentities = new[] { identity }, CanonicalCode = canonical, QueryVariants = variants.Distinct(StringComparer.OrdinalIgnoreCase).ToArray() };

        private static IReadOnlyDictionary<string, string> LoadPrefixes()
        {
            var assembly = typeof(MediaIdentifier).Assembly;
            using (var stream = assembly.GetManifestResourceStream(assembly.GetManifestResourceNames().Single(x => x.EndsWith("amateur-prefixes.json", StringComparison.Ordinal))))
            {
                var serializer = new DataContractJsonSerializer(typeof(Dictionary<string, string>), new DataContractJsonSerializerSettings { UseSimpleDictionaryFormat = true });
                return (Dictionary<string, string>)serializer.ReadObject(stream);
            }
        }
    }
}
