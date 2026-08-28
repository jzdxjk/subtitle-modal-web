using System;
using System.Linq;

namespace SubtitleCloudPlugin;

public static class PathMapping
{
    public static string Apply(string path, string mappings)
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
            if (normalized.Equals(source, StringComparison.OrdinalIgnoreCase) || normalized.StartsWith(source + "/", StringComparison.OrdinalIgnoreCase))
                return item.Target + normalized.Substring(source.Length);
        }
        return path;
    }
}
