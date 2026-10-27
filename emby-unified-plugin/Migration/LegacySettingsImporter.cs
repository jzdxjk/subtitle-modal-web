using System;
using System.IO;
using System.Linq;
using System.Xml;
using System.Xml.Linq;
using MediaBrowser.Model.Serialization;

namespace Emby.SubtitleAssistant.Migration;

internal static class LegacySettingsImporter
{
    public static PluginConfiguration Merge(string directory, PluginConfiguration current, IJsonSerializer json)
    {
        try
        {
            var local = Read<LocalSettings>(directory, "MeiamSub.LocalPool.json", json);
            var thunder = Read<ThunderSettings>(directory, "ThunderSubtitle.json", json);
            var pool = Read<PoolSettings>(directory, "ChickenRicePool.json", json);
            var cloudFile = Path.Combine(directory, "SubtitleCloudPlugin.xml");
            XElement cloud = null;
            if (File.Exists(cloudFile))
            {
                var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = 1048576 };
                using (var reader = XmlReader.Create(cloudFile, settings)) cloud = XDocument.Load(reader).Root;
                if (cloud == null || cloud.Name.LocalName != "PluginConfiguration") throw new InvalidDataException();
            }
            var result = MigrationRunner.Clone(current, json);
            if (local?.SubtitleLibraryPaths != null) result.LocalPaths = local.SubtitleLibraryPaths;
            if (pool?.PoolBaseUrl != null) result.PoolUrl = pool.PoolBaseUrl;
            if (pool?.RequestTimeoutSeconds != null) result.PoolTimeoutSeconds = pool.RequestTimeoutSeconds.Value;
            if (thunder?.EnableAutoDownloadOnNewMedia != null || pool?.EnableAutoDownloadOnNewMedia != null)
                result.AutoDownloadOnNewMedia = thunder?.EnableAutoDownloadOnNewMedia == true || pool?.EnableAutoDownloadOnNewMedia == true;
            if (cloud != null)
            {
                string Value(string name) => cloud.Elements().SingleOrDefault(x => x.Name.LocalName == name)?.Value;
                result.CloudServiceUrl = Value("ServiceUrl") ?? result.CloudServiceUrl;
                result.CloudApiToken = Value("ApiToken") ?? result.CloudApiToken;
                result.CloudPathMappings = Value("PathMappings") ?? result.CloudPathMappings;
            }
            result.Validate();
            return result;
        }
        catch { throw new MigrationException("旧字幕插件配置无法完整解析或校验，未导入任何配置。"); }
    }
    private static T Read<T>(string directory, string filename, IJsonSerializer json) where T : class
    {
        var path = Path.Combine(directory, filename);
        if (!File.Exists(path)) return null;
        if (new FileInfo(path).Length > 1048576) throw new InvalidDataException();
        return json.DeserializeFromString<T>(File.ReadAllText(path)) ?? throw new InvalidDataException();
    }
    public sealed class LocalSettings { public string SubtitleLibraryPaths { get; set; } }
    public sealed class ThunderSettings { public bool? EnableAutoDownloadOnNewMedia { get; set; } }
    public sealed class PoolSettings
    {
        public string PoolBaseUrl { get; set; }
        public int? RequestTimeoutSeconds { get; set; }
        public bool? EnableAutoDownloadOnNewMedia { get; set; }
        public string SimplifiedChineseLanguage { get; set; }
        public string TraditionalChineseLanguage { get; set; }
    }
}
