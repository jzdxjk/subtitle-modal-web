using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Controller.Net;
using MediaBrowser.Model.Services;

namespace Emby.SubtitleAssistant.Web;

[Route("/SubtitleAssistant/proxy/test", "POST")]
public sealed class ProxyTestRequest
{
    public string Url { get; set; }
    public string Purpose { get; set; }
}

public sealed class SettingsResult
{
    public bool Ok { get; set; }
    public string Error { get; set; }
    public SettingsSnapshot Settings { get; set; }
    public long? LatencyMs { get; set; }
    public string Route { get; set; }
}

[Authenticated(Roles = "Admin")]
public sealed class SettingsService : IService, IRequiresRequest
{
    private static readonly object SaveLock = new object();
    private static readonly IReadOnlyDictionary<NetworkPurpose,string> ProxyTestTargets =
        new Dictionary<NetworkPurpose,string>
        {
            [NetworkPurpose.Thunder] = "https://www.google.com/generate_204",
            [NetworkPurpose.Cloud] = "https://www.google.com/generate_204",
            [NetworkPurpose.Updates] = PluginConfiguration.OfficialUpdateManifestUrl
        };
    private readonly IAuthorizationContext _authorization;
    public IRequest Request { get; set; }
    public SettingsService(IAuthorizationContext authorization) => _authorization = authorization;

    public SettingsSnapshot Get(GetSettingsRequest request)
    {
        AdminAccess.Require(_authorization, Request);
        return SettingsEditor.Snapshot(Plugin.CurrentConfiguration);
    }

    public SettingsResult Post(SaveSettingsRequest request)
    {
        AdminAccess.Require(_authorization, Request);
        try
        {
            lock (SaveLock)
            {
                var next = SettingsEditor.Apply(Plugin.CurrentConfiguration, request);
                if (Plugin.Instance == null) return new SettingsResult { Ok = false, Error = "插件尚未初始化。" };
                Plugin.Instance.UpdateConfiguration(next);
                return new SettingsResult { Ok = true, Settings = SettingsEditor.Snapshot(next) };
            }
        }
        catch (ArgumentException error) { return new SettingsResult { Ok = false, Error = error.Message }; }
        catch { return new SettingsResult { Ok = false, Error = "保存失败，请查看 Emby 日志。" }; }
    }

    public async Task<object> Post(ProxyTestRequest request)
    {
        AdminAccess.Require(_authorization, Request);
        if (request == null || !Enum.TryParse(request.Purpose, true, out NetworkPurpose purpose) ||
            !Enum.IsDefined(typeof(NetworkPurpose), purpose))
            return new SettingsResult { Ok = false, Error = "请选择有效的流量用途。" };
        var target = string.IsNullOrWhiteSpace(request.Url) ? ProxyTestTargets[purpose] : request.Url;
        if (!Uri.TryCreate(target, UriKind.Absolute, out var uri) ||
            (uri.Scheme != "https" && uri.Scheme != "http") || !string.IsNullOrEmpty(uri.UserInfo))
            return new SettingsResult { Ok = false, Error = "测试目标地址无效。" };
        var route = PluginHttpClient.ShouldProxy(Plugin.CurrentConfiguration.Proxy, purpose, uri) ? "Proxy" : "Direct";
        var stopwatch = Stopwatch.StartNew();
        try
        {
            await PluginHttpClient.Shared.GetBytesAsync(uri.AbsoluteUri, purpose, CancellationToken.None,
                timeoutSeconds: 15, maxBytes: 65536).ConfigureAwait(false);
            stopwatch.Stop();
            return new SettingsResult { Ok = true, LatencyMs = stopwatch.ElapsedMilliseconds, Route = route };
        }
        catch (OperationCanceledException)
        {
            stopwatch.Stop();
            return new SettingsResult { Ok = false, Error = "连接超时。", Route = route };
        }
        catch
        {
            stopwatch.Stop();
            return new SettingsResult { Ok = false, Error = "连接失败，请检查当前已保存的代理与路由设置。", Route = route };
        }
    }
}
