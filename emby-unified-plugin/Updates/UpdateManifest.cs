using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;

namespace Emby.SubtitleAssistant.Updates;

public sealed class UpdateManifest
{
    public string version { get; set; }
    public string download_url { get; set; }
    public string sha256 { get; set; }
    public string plugin_id { get; set; }
    public string channel { get; set; }
    public Dictionary<string, string> minimum_server_versions { get; set; }
    private static readonly Dictionary<string, Version> Baselines = new Dictionary<string, Version>
    {
        ["4.8"] = new Version(4, 8, 11, 0), ["4.9"] = new Version(4, 9, 1, 80), ["4.10"] = new Version(4, 10, 0, 40)
    };

    public Version Validate(Version serverVersion)
    {
        var target = ValidatePackageMetadata();
        if (minimum_server_versions == null) throw new InvalidDataException("更新清单缺少兼容版本范围。");
        foreach (var family in Baselines)
        {
            if (!minimum_server_versions.TryGetValue(family.Key, out var text))
                throw new InvalidDataException("更新清单缺少兼容版本范围。");
            var minimum = ParseFourParts(text);
            if (minimum.ToString(2) != family.Key || minimum < family.Value)
                throw new InvalidDataException("更新清单的兼容版本范围无效。");
        }
        if (serverVersion == null || !Baselines.TryGetValue(serverVersion.ToString(2), out var baseline) ||
            serverVersion < baseline || serverVersion < ParseFourParts(minimum_server_versions[serverVersion.ToString(2)]))
            throw new InvalidDataException("此更新不兼容当前 Emby 版本。");
        return target;
    }

    internal Version ValidatePackageMetadata()
    {
        var target = ParseFourParts(version);
        if (channel != "stable" || !Guid.TryParse(plugin_id, out var id) || id != Plugin.PluginId)
            throw new InvalidDataException("更新清单的插件身份或发布通道不匹配。");
        if (!Regex.IsMatch(sha256 ?? "", @"\A[0-9a-fA-F]{64}\z")) throw new InvalidDataException("更新清单的 SHA256 无效。");
        if (!Uri.TryCreate(download_url, UriKind.Absolute, out var url) || (url.Scheme != "http" && url.Scheme != "https") ||
            !string.IsNullOrEmpty(url.UserInfo) || !string.IsNullOrEmpty(url.Fragment))
            throw new InvalidDataException("更新清单的下载地址无效。");
        return target;
    }

    private static Version ParseFourParts(string value)
    {
        if (!Regex.IsMatch(value ?? "", @"\A\d+\.\d+\.\d+\.\d+\z") || !Version.TryParse(value, out var result) ||
            result.Major > ushort.MaxValue || result.Minor > ushort.MaxValue || result.Build > ushort.MaxValue || result.Revision > ushort.MaxValue)
            throw new InvalidDataException("更新清单必须使用有效的四段正式版本号。");
        return result;
    }
}
