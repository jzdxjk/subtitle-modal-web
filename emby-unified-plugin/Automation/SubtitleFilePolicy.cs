using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;

namespace Emby.SubtitleAssistant.Automation;

internal enum SubtitleFileDecision
{
    None,
    ChineseFilenameMarker,
    MatchingSubtitle,
    DirectoryReadFailure
}

internal static class SubtitleFilePolicy
{
    private static readonly Regex ChineseCodeMarker = new Regex(
        @"-c(?:$|[._\s-])",RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    internal static SubtitleFileDecision Check(string mediaPath, Action<Exception> onDirectoryFailure = null)
    {
        var mediaStem = Path.GetFileNameWithoutExtension(mediaPath ?? string.Empty);
        if (HasChineseMarker(mediaStem)) return SubtitleFileDecision.ChineseFilenameMarker;

        var directory = Path.GetDirectoryName(mediaPath ?? string.Empty);
        if (string.IsNullOrWhiteSpace(directory) || string.IsNullOrWhiteSpace(mediaStem))
        {
            onDirectoryFailure?.Invoke(new ArgumentException("Media path has no directory or filename."));
            return SubtitleFileDecision.DirectoryReadFailure;
        }

        try
        {
            var subFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var idxFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var path in Directory.EnumerateFiles(directory,"*",SearchOption.TopDirectoryOnly))
            {
                var extension = Path.GetExtension(path);
                var candidateStem = Path.GetFileNameWithoutExtension(path);
                if (!MatchesMediaStem(candidateStem,mediaStem)) continue;
                switch (extension.ToLowerInvariant())
                {
                    case ".ass":
                    case ".srt":
                    case ".ssa":
                    case ".vtt":
                        return SubtitleFileDecision.MatchingSubtitle;
                    case ".sub": subFiles.Add(candidateStem); break;
                    case ".idx": idxFiles.Add(candidateStem); break;
                }
            }
            if (subFiles.Overlaps(idxFiles)) return SubtitleFileDecision.MatchingSubtitle;
            return SubtitleFileDecision.None;
        }
        catch (Exception error) when (error is IOException || error is UnauthorizedAccessException ||
            error is ArgumentException || error is NotSupportedException)
        {
            onDirectoryFailure?.Invoke(error);
            return SubtitleFileDecision.DirectoryReadFailure;
        }
    }

    private static bool MatchesMediaStem(string candidateStem, string mediaStem)
    {
        if (string.Equals(candidateStem,mediaStem,StringComparison.OrdinalIgnoreCase)) return true;
        return candidateStem.StartsWith(mediaStem + ".",StringComparison.OrdinalIgnoreCase);
    }

    private static bool HasChineseMarker(string mediaStem)
    {
        var positive = (mediaStem ?? string.Empty)
            .Replace("无中文字幕",string.Empty,StringComparison.Ordinal)
            .Replace("无简中",string.Empty,StringComparison.Ordinal)
            .Replace("无中字",string.Empty,StringComparison.Ordinal);
        return positive.Contains("中文字幕",StringComparison.Ordinal) || positive.Contains("简中",StringComparison.Ordinal) ||
            positive.Contains("中字",StringComparison.Ordinal) || ChineseCodeMarker.IsMatch(positive);
    }
}
