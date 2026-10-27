using System;
using MediaBrowser.Model.Services;

namespace Emby.SubtitleAssistant.Web;

[Route("/SubtitleAssistant/settings", "GET")]
public sealed class GetSettingsRequest { }

[Route("/SubtitleAssistant/settings", "POST")]
public sealed class SaveSettingsRequest
{
    public string LocalPaths { get; set; }
    public int? LocalMaxResults { get; set; }
    public int? ThunderMaxResults { get; set; }
    public int? ThunderTimeoutSeconds { get; set; }
    public int? PoolMaxResults { get; set; }
    public int? PoolTimeoutSeconds { get; set; }
    public string CloudServiceUrl { get; set; }
    public string CloudApiToken { get; set; }
    public bool ClearCloudApiToken { get; set; }
    public string CloudPathMappings { get; set; }
    public bool? AutoDownloadOnNewMedia { get; set; }
    public string SimplifiedChineseLanguage { get; set; }
    public string TraditionalChineseLanguage { get; set; }
    public string UpdateManifestUrl { get; set; }
    public ProxySettingsUpdate Proxy { get; set; }
}

public sealed class ProxySettingsUpdate
{
    public bool? Enabled { get; set; }
    public string Address { get; set; }
    public string Username { get; set; }
    public string Password { get; set; }
    public bool ClearPassword { get; set; }
    public bool? BypassLocal { get; set; }
    public string BypassHosts { get; set; }
    public bool? Thunder { get; set; }
    public bool? Pool { get; set; }
    public bool? Cloud { get; set; }
    public bool? Updates { get; set; }
}

public sealed class SettingsSnapshot
{
    public string Version { get; set; }
    public string LocalPaths { get; set; }
    public int LocalMaxResults { get; set; }
    public int ThunderMaxResults { get; set; }
    public int ThunderTimeoutSeconds { get; set; }
    public int PoolMaxResults { get; set; }
    public int PoolTimeoutSeconds { get; set; }
    public string CloudServiceUrl { get; set; }
    public bool HasCloudApiToken { get; set; }
    public string CloudPathMappings { get; set; }
    public bool AutoDownloadOnNewMedia { get; set; }
    public ProxySnapshot Proxy { get; set; }
}

public sealed class ProxySnapshot
{
    public bool Enabled { get; set; }
    public string Address { get; set; }
    public string Username { get; set; }
    public bool HasPassword { get; set; }
    public bool BypassLocal { get; set; }
    public string BypassHosts { get; set; }
    public bool Thunder { get; set; }
    public bool Pool { get; set; }
    public bool Cloud { get; set; }
    public bool Updates { get; set; }
}

public static class SettingsEditor
{
    public static SettingsSnapshot Snapshot(PluginConfiguration configuration)
    {
        var c = configuration;
        var p = c.Proxy ?? new ProxyConfiguration();
        return new SettingsSnapshot
        {
            Version = typeof(Plugin).Assembly.GetName().Version?.ToString() ?? "",
            LocalPaths = c.LocalPaths, LocalMaxResults = c.LocalMaxResults, ThunderMaxResults = c.ThunderMaxResults,
            ThunderTimeoutSeconds = c.ThunderTimeoutSeconds,
            PoolMaxResults = c.PoolMaxResults, PoolTimeoutSeconds = c.PoolTimeoutSeconds,
            CloudServiceUrl = c.CloudServiceUrl, HasCloudApiToken = !string.IsNullOrEmpty(c.CloudApiToken),
            CloudPathMappings = c.CloudPathMappings, AutoDownloadOnNewMedia = c.AutoDownloadOnNewMedia,
            Proxy = new ProxySnapshot
            {
                Enabled = p.Enabled, Address = p.Address, Username = p.Username, HasPassword = !string.IsNullOrEmpty(p.Password),
                BypassLocal = p.BypassLocal, BypassHosts = p.BypassHosts,
                Thunder = p.Thunder, Pool = p.Pool, Cloud = p.Cloud, Updates = p.Updates
            }
        };
    }

    public static PluginConfiguration Apply(PluginConfiguration configuration, SaveSettingsRequest update)
    {
        if (update == null) throw new ArgumentException("缺少设置。");
        var c = configuration;
        var p = c.Proxy ?? new ProxyConfiguration();
        var u = update.Proxy;
        var next = new PluginConfiguration
        {
            LocalPaths = update.LocalPaths ?? c.LocalPaths,
            LocalMaxResults = update.LocalMaxResults ?? c.LocalMaxResults,
            ThunderMaxResults = update.ThunderMaxResults ?? c.ThunderMaxResults,
            ThunderTimeoutSeconds = update.ThunderTimeoutSeconds ?? c.ThunderTimeoutSeconds,
            PoolMaxResults = update.PoolMaxResults ?? c.PoolMaxResults,
            // The pool address is fixed in code and is not user-configurable.
            PoolUrl = PluginConfiguration.OfficialPoolUrl,
            PoolTimeoutSeconds = update.PoolTimeoutSeconds ?? c.PoolTimeoutSeconds,
            CloudServiceUrl = update.CloudServiceUrl ?? c.CloudServiceUrl,
            CloudApiToken = Secret(c.CloudApiToken, update.CloudApiToken, update.ClearCloudApiToken),
            CloudPathMappings = update.CloudPathMappings ?? c.CloudPathMappings,
            AutoDownloadOnNewMedia = update.AutoDownloadOnNewMedia ?? c.AutoDownloadOnNewMedia,
            // The language markers are fixed in code; hidden legacy values must not override them.
            SimplifiedChineseLanguage = ChineseSubtitleLanguage.Simplified,
            TraditionalChineseLanguage = ChineseSubtitleLanguage.Traditional,
            // The manifest URL is not user-configurable; always point at the official pointer release.
            UpdateManifestUrl = PluginConfiguration.OfficialUpdateManifestUrl,
            MigrationVersion = c.MigrationVersion,
            Proxy = new ProxyConfiguration
            {
                Enabled = u?.Enabled ?? p.Enabled, Address = u?.Address ?? p.Address,
                Username = u?.Username ?? p.Username, Password = Secret(p.Password, u?.Password, u?.ClearPassword ?? false),
                BypassLocal = u?.BypassLocal ?? p.BypassLocal, BypassHosts = u?.BypassHosts ?? p.BypassHosts,
                Thunder = u?.Thunder ?? p.Thunder, Pool = u?.Pool ?? p.Pool,
                Cloud = u?.Cloud ?? p.Cloud, Updates = u?.Updates ?? p.Updates
            }
        };
        next.Validate();
        return next;
    }

    private static string Secret(string current, string replacement, bool clear)
    {
        if (clear && !string.IsNullOrEmpty(replacement)) throw new ArgumentException("清除密钥与填写新密钥不能同时选择。");
        return clear ? "" : string.IsNullOrEmpty(replacement) ? current ?? "" : replacement;
    }
}
