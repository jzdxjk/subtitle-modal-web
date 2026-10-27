using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Providers;
namespace Emby.SubtitleAssistant.Providers
{
    public sealed class LocalSubtitleProvider : ISubtitleProvider, IHasOrder
    {
        private readonly ILogger _logger;
        public LocalSubtitleProvider(ILogManager logManager) { _logger = logManager?.GetLogger(GetType().Name); }
        public string Name => ProviderNames.Local;
        public int Order => 80;
        public IEnumerable<VideoContentType> SupportedMediaTypes => new[] { VideoContentType.Movie, VideoContentType.Episode };
        public Task<IEnumerable<RemoteSubtitleInfo>> Search(SubtitleSearchRequest request, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var identifier = MediaIdentifier.TryParse(request?.MediaPath);
            if (identifier == null) return Task.FromResult<IEnumerable<RemoteSubtitleInfo>>(Array.Empty<RemoteSubtitleInfo>());
            var candidates = new List<SubtitleCandidate>();
            var index = 0;
            foreach (var path in Files(Roots()).OrderBy(x => x, StringComparer.Ordinal))
            {
                ct.ThrowIfCancellationRequested();
                var format = Path.GetExtension(path).TrimStart('.').ToLowerInvariant();
                if ((!SubtitleContent.IsSupported(format) && format != "zip") || !identifier.Matches(Path.GetFileNameWithoutExtension(path))) continue;
                try
                {
                    if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) continue;
                    if (new FileInfo(path).Length > 16777216) continue;
                    foreach (var document in SubtitleContent.ReadAll(File.ReadAllBytes(path), format, Path.GetFileName(path)))
                    {
                        if (!SubtitleContent.AcceptLanguage(request.Language, document.Language)) continue;
                        if (MediaIdentifier.ContainsAnyCode(document.Name) && !identifier.Matches(document.Name)) continue;
                        var payload = new DownloadPayload { Path = path, Format = document.Format, ContentHash = document.ContentHash, EntryName = document.Name, Name = Path.GetFileName(path), Language = request.Language, MediaPath = request.MediaPath };
                        candidates.Add(new SubtitleCandidate { Id = ProviderSupport.Encode(payload), Name = document.Name, Format = document.Format, Language = document.Language, SizeBytes = document.Bytes.LongLength, DurationSeconds = document.DurationSeconds, ContentHash = document.ContentHash, StableOrder = index++ });
                    }
                }
                catch (IOException) { _logger?.Warn("Local subtitle file could not be read."); }
                catch (UnauthorizedAccessException) { _logger?.Warn("Local subtitle file access was denied."); }
            }
            return Task.FromResult(ProviderSupport.Complete(ProviderSupport.Deduplicate(candidates), request, Name, Plugin.CurrentConfiguration.LocalMaxResults, "字幕轴"));
        }
        public Task<SubtitleResponse> GetSubtitles(string id, CancellationToken ct)
        {
            ct.ThrowIfCancellationRequested();
            var payload = ProviderSupport.Decode(id);
            if (!SubtitleContent.IsSupported(payload.Format)) throw new InvalidDataException("Invalid subtitle format.");
            var comparison = Path.DirectorySeparatorChar == '\\' ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
            Exception failure = null;
            foreach (var location in new[] { payload.Path }.Concat(payload.AlternatePaths ?? Array.Empty<string>()).Where(x => !string.IsNullOrEmpty(x)).Distinct(StringComparer.Ordinal))
            {
                try
                {
                    var path = NormalizePath(location);
                    var root = Roots().FirstOrDefault(x => path.StartsWith(x.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, comparison));
                    if (root == null) throw new UnauthorizedAccessException("Subtitle path is outside configured libraries.");
                    var extension = Path.GetExtension(path).TrimStart('.').ToLowerInvariant();
                    if (!SubtitleContent.IsSupported(extension) && extension != "zip") throw new InvalidDataException("Invalid subtitle file extension.");
                    for (var current = path; !string.Equals(current.TrimEnd(Path.DirectorySeparatorChar), root.TrimEnd(Path.DirectorySeparatorChar), comparison); current = Path.GetDirectoryName(current))
                        if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new UnauthorizedAccessException("Subtitle paths may not traverse symbolic links.");
                    if (new FileInfo(path).Length > 16777216) throw new InvalidDataException("Subtitle file is too large.");
                    return Task.FromResult(ProviderSupport.Response(payload, ProviderSupport.SelectDocument(File.ReadAllBytes(path), payload)));
                }
                catch (IOException ex) { failure = ex; }
                catch (UnauthorizedAccessException ex) { failure = ex; }
            }
            throw failure ?? new InvalidDataException("Local subtitle file is no longer available.");
        }
        private static string NormalizePath(string path)
        {
            if (Uri.TryCreate(path, UriKind.Absolute, out var uri) && uri.IsFile) path = uri.LocalPath;
            path = Uri.UnescapeDataString(path ?? "").Replace('\\', Path.DirectorySeparatorChar).Replace('/', Path.DirectorySeparatorChar);
            return Path.GetFullPath(path);
        }
        private static string[] Roots() => (Plugin.CurrentConfiguration.LocalPaths ?? "").Split(new[] { ';', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(x => NormalizePath(x.Trim())).Where(Directory.Exists).Distinct().ToArray();
        private static IEnumerable<string> Files(IEnumerable<string> roots)
        {
            var pending = new Stack<string>(roots.Reverse());
            var visited = new HashSet<string>(Path.DirectorySeparatorChar == '\\' ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
            while (pending.Count != 0)
            {
                var directory = pending.Pop();
                if (!visited.Add(directory)) continue;
                string[] files;
                string[] directories;
                try { files = Directory.GetFiles(directory); directories = Directory.GetDirectories(directory); }
                catch (IOException) { continue; }
                catch (UnauthorizedAccessException) { continue; }
                foreach (var file in files) yield return file;
                foreach (var child in directories)
                {
                    FileAttributes attributes;
                    try { attributes = File.GetAttributes(child); }
                    catch (IOException) { continue; }
                    catch (UnauthorizedAccessException) { continue; }
                    if ((attributes & FileAttributes.ReparsePoint) == 0) pending.Push(child);
                }
            }
        }
    }
}
