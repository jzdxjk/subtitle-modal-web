using System;
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
}

[Authenticated(Roles = "Admin")]
public sealed class SettingsService : IService, IRequiresRequest
{
    private static readonly object SaveLock = new object();
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
        if (request == null || !Uri.TryCreate(request.Url, UriKind.Absolute, out var uri) ||
            (uri.Scheme != "https" && uri.Scheme != "http") || !string.IsNullOrEmpty(uri.UserInfo) ||
            !Enum.TryParse(request.Purpose, true, out NetworkPurpose purpose) || !Enum.IsDefined(typeof(NetworkPurpose), purpose))
            return new SettingsResult { Ok = false, Error = "请选择有效的测试地址和流量用途。" };
        try
        {
            await PluginHttpClient.Shared.GetBytesAsync(uri.AbsoluteUri, purpose, CancellationToken.None,
                timeoutSeconds: 15, maxBytes: 65536).ConfigureAwait(false);
            return new SettingsResult { Ok = true };
        }
        catch { return new SettingsResult { Ok = false, Error = "连接失败，请检查当前已保存的代理、路由和测试地址。" }; }
    }
}
