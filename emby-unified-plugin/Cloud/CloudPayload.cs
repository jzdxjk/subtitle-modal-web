using System;
using System.Collections.Generic;
using System.Linq;

namespace Emby.SubtitleAssistant.Cloud;

public sealed class CloudMediaInfo
{
    public string ItemId { get; set; }
    public string Path { get; set; }
    public string Title { get; set; }
    public string Type { get; set; }
    public string AvCode { get; set; }
    public string PosterUrl { get; set; }
    public string StrmContent { get; set; }
    public CloudAudioInfo Audio { get; set; }
}

public sealed class CloudAudioInfo
{
    public int Index { get; set; }
    public string Codec { get; set; }
    public int Channels { get; set; }
    public int BitRate { get; set; }
    public int SampleRate { get; set; }
}

public static class CloudPayload
{
    public static string MapPath(string path, string mappings)
    {
        var candidates = (mappings ?? "").Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(line => line.Split(new[] { '=' }, 2))
            .Where(parts => parts.Length == 2 && !string.IsNullOrWhiteSpace(parts[0]))
            .Select(parts => new { Source = parts[0].Trim().TrimEnd('\\', '/'), Target = parts[1].Trim().TrimEnd('\\', '/') })
            .OrderByDescending(item => item.Source.Length);
        var normalized = (path ?? "").Replace('\\', '/');
        foreach (var item in candidates)
        {
            var source = item.Source.Replace('\\', '/');
            if (normalized.Equals(source, StringComparison.OrdinalIgnoreCase) ||
                normalized.StartsWith(source + "/", StringComparison.OrdinalIgnoreCase))
                return item.Target + normalized.Substring(source.Length);
        }
        return path;
    }

    public static string TaskTypeFor(string path, string strmContent)
    {
        if (!(path ?? "").EndsWith(".strm", StringComparison.OrdinalIgnoreCase)) return "native";
        var source = (strmContent ?? "").Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(line => line.Trim()).FirstOrDefault(line => line.Length > 0 && !line.StartsWith("#", StringComparison.Ordinal));
        if (string.IsNullOrEmpty(source)) return "native";
        return source.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || source.StartsWith("https://", StringComparison.OrdinalIgnoreCase)
            ? "strm-http" : "strm-local";
    }

    public static Dictionary<string, object> Create(CloudMediaInfo media, string mappings)
    {
        if (media == null || !(media.Type == "Movie" || media.Type == "Episode"))
            throw new ArgumentException("仅支持电影和单集视频。");
        if (string.IsNullOrWhiteSpace(media.Path)) throw new ArgumentException("未找到媒体路径。");
        var result = new Dictionary<string, object>
        {
            ["input_path"] = MapPath(media.Path, mappings),
            ["emby_item_id"] = media.ItemId ?? "",
            ["display_title"] = media.Title ?? "",
            ["av_code"] = media.AvCode ?? "",
            ["poster_url"] = media.PosterUrl ?? "",
            ["task_type"] = TaskTypeFor(media.Path, media.StrmContent),
            ["formats"] = new[] { "srt" },
            ["overwrite"] = false
        };
        var audio = media.Audio;
        if (audio != null && audio.BitRate > 0 && audio.Channels > 0)
            result["audio_stream"] = new Dictionary<string, object>
            {
                ["index"] = audio.Index, ["codec"] = audio.Codec ?? "", ["channels"] = audio.Channels,
                ["bit_rate"] = audio.BitRate, ["sample_rate"] = audio.SampleRate
            };
        return result;
    }
}
