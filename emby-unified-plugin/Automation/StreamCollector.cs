using System;
using System.Collections.Generic;
using MediaBrowser.Model.Entities;

namespace Emby.SubtitleAssistant.Automation;

/// <summary>
/// Merges media streams from independent, individually fallible sources without letting a
/// single failing lookup abort subtitle completion. Media source lookups can throw
/// <see cref="ArgumentOutOfRangeException"/> for freshly ingested items (for example .strm
/// entries whose media streams are not resolvable yet); those failures are reported and the
/// remaining sources are still used.
/// </summary>
internal static class StreamCollector
{
    internal const string ItemStreamsStage = "item-streams";
    internal const string MediaSourceStreamsStage = "media-source-streams";

    internal static MediaStream[] Collect(
        Func<IEnumerable<MediaStream>> itemStreams,
        Func<long, IEnumerable<MediaStream>> mediaSourceStreams,
        long internalId,
        Action<string, Exception> onFailure)
    {
        var collected = new List<MediaStream>();
        Read(itemStreams, ItemStreamsStage, collected, onFailure);

        // A non-positive internal id cannot be resolved by the media source manager; skip that
        // lookup instead of asking Emby to resolve an id that is not persisted yet.
        if (internalId > 0)
            Read(mediaSourceStreams == null ? null : () => mediaSourceStreams(internalId),
                MediaSourceStreamsStage, collected, onFailure);

        return Deduplicate(collected);
    }

    private static void Read(Func<IEnumerable<MediaStream>> source, string stage,
        ICollection<MediaStream> collected, Action<string, Exception> onFailure)
    {
        if (source == null) return;
        try
        {
            var values = source();
            if (values == null) return;
            foreach (var stream in values)
                if (stream != null) collected.Add(stream);
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception error) { onFailure?.Invoke(stage, error); }
    }

    private static MediaStream[] Deduplicate(IEnumerable<MediaStream> streams)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var result = new List<MediaStream>();
        foreach (var stream in streams)
        {
            var key = string.Join("|", stream.Type, stream.Index, stream.Language ?? string.Empty,
                stream.IsExternal, stream.IsDefault, stream.Path ?? string.Empty,
                stream.Codec ?? string.Empty, stream.Title ?? string.Empty);
            if (seen.Add(key)) result.Add(stream);
        }
        return result.ToArray();
    }
}
