using MediaBrowser.Model.Plugins;
using System;

namespace Emby.SubtitleAssistant;

public sealed class PluginConfiguration : BasePluginConfiguration
{
    public string LocalPaths { get; set; } = "";
    public int LocalMaxResults { get; set; } = 5;
    public int ThunderMaxResults { get; set; } = 5;
    public int PoolMaxResults { get; set; } = 5;
    public string PoolUrl { get; set; } = "https://chickenrice-subtitle-pool.jzdxjk.workers.dev";
    public int PoolTimeoutSeconds { get; set; } = 15;
    public string CloudServiceUrl { get; set; } = "";
    public string CloudApiToken { get; set; } = "";
    public string CloudPathMappings { get; set; } = "";
    public bool AutoDownloadOnNewMedia { get; set; }
    public string SimplifiedChineseLanguage { get; set; } = "zh-CN";
    public string TraditionalChineseLanguage { get; set; } = "zh-TW";
    public int MigrationVersion { get; set; }
    public string UpdateManifestUrl { get; set; } = "https://github.com/jzdxjk/subtitle-modal-web/releases/download/emby-subtitle-assistant-update/update.json";
    public ProxyConfiguration Proxy { get; set; } = new ProxyConfiguration();
    public void Validate()
    {
        if (LocalMaxResults < 1 || ThunderMaxResults < 1 || PoolMaxResults < 1)
            throw new ArgumentException("最大展示结果数必须为正整数。");
        if (PoolTimeoutSeconds < 1 || PoolTimeoutSeconds > 120)
            throw new ArgumentException("海南鸡请求超时必须在1到120秒之间。");
        ValidateServiceUrl(PoolUrl, "海南鸡服务地址", false);
        ValidateServiceUrl(CloudServiceUrl, "字幕云服务地址", true);
        ValidateServiceUrl(UpdateManifestUrl, "插件更新清单地址", false);
        if (Proxy == null) throw new ArgumentException("缺少代理配置。");
        if (Proxy.Enabled) Proxy.ValidateAddress();
    }

    private static void ValidateServiceUrl(string value, string label, bool allowEmpty)
    {
        if (allowEmpty && string.IsNullOrWhiteSpace(value)) return;
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) ||
            (uri.Scheme != "http" && uri.Scheme != "https") ||
            !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Fragment))
            throw new ArgumentException(label + "必须是无内嵌凭据的HTTP或HTTPS地址。");
    }
}

public sealed class ProxyConfiguration
{
    public bool Enabled { get; set; }
    public string Address { get; set; } = "";
    public string Username { get; set; } = "";
    public string Password { get; set; } = "";
    public string BypassHosts { get; set; } = "";
    public bool Thunder { get; set; } = true;
    public bool Pool { get; set; } = true;
    public bool Cloud { get; set; }
    public bool Updates { get; set; } = true;
    public bool BypassLocal { get; set; } = true;

    internal Uri ValidateAddress()
    {
        if (!Uri.TryCreate(Address, UriKind.Absolute, out var uri) ||
            (uri.Scheme != "http" && uri.Scheme != "socks5") ||
            string.IsNullOrWhiteSpace(uri.Host) || !string.IsNullOrEmpty(uri.UserInfo) ||
            uri.AbsolutePath != "/" || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment))
            throw new ArgumentException("代理地址必须为http://主机:端口或socks5://主机:端口，认证信息请填写单独字段。");
        return uri;
    }
}
