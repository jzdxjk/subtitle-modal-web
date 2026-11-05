using System;
using System.Reflection;
using System.Linq;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Cloud;
using Emby.SubtitleAssistant.Web;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Net;
using MediaBrowser.Model.Services;
using MediaBrowser.Model.Users;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class WebServiceSecurityTests
{
    [Fact]
    public void PublicAsynchronousServiceHandlersUseEmbyTaskObjectResponseContract()
    {
        var services = new[] { typeof(SettingsService), typeof(CloudAdminService) };
        foreach (var service in services)
        foreach (var method in service.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly)
            .Where(method => method.ReturnType.IsGenericType && method.ReturnType.GetGenericTypeDefinition() == typeof(Task<>)))
            Assert.True(method.ReturnType == typeof(Task<object>), service.Name + "." + method.Name + " must return Task<object> for Emby 4.8 response serialization");
    }

    [Fact]
    public async Task RegularUserCannotReadSaveTestProxyListJobsOrSubmit()
    {
        var authorization = DispatchProxy.Create<IAuthorizationContext, WebAuthorizationProxy>();
        ((WebAuthorizationProxy)authorization).Info = new AuthorizationInfo { User = new User { Policy = new UserPolicy() } };
        var request = DispatchProxy.Create<IRequest, WebRequestProxy>();
        var settings = new SettingsService(authorization) { Request = request };
        Assert.Throws<SecurityException>(() => settings.Get(new GetSettingsRequest()));
        Assert.Throws<SecurityException>(() => settings.Post(new SaveSettingsRequest { LocalMaxResults = 99 }));
        await Assert.ThrowsAsync<SecurityException>(() => settings.Post(new ProxyTestRequest { Url = "https://example.invalid", Purpose = "Thunder" }));
        var cloud = new CloudAdminService(authorization, null, null) { Request = request };
        await Assert.ThrowsAsync<SecurityException>(() => cloud.Get(new GetCloudJobsRequest()));
        await Assert.ThrowsAsync<SecurityException>(() => cloud.Post(new SubmitCloudJobRequest { ItemId = "42" }));
    }

    [Fact]
    public void AdministratorCanReadSanitizedSettingsOnly()
    {
        var authorization = DispatchProxy.Create<IAuthorizationContext, WebAuthorizationProxy>();
        ((WebAuthorizationProxy)authorization).Info = new AuthorizationInfo { User = new User { Policy = new UserPolicy { IsAdministrator = true } } };
        using var configuration = Plugin.OverrideConfigurationForTests(new PluginConfiguration { CloudApiToken = "must-not-be-returned" });
        var settings = new SettingsService(authorization) { Request = DispatchProxy.Create<IRequest, WebRequestProxy>() };
        var result = settings.Get(new GetSettingsRequest());
        Assert.True(result.HasCloudApiToken);
        Assert.Null(result.GetType().GetProperty("CloudApiToken"));
    }
}

public class WebAuthorizationProxy : DispatchProxy
{
    public AuthorizationInfo Info;
    protected override object Invoke(MethodInfo method, object[] args) => Info;
}

public class WebRequestProxy : DispatchProxy
{
    protected override object Invoke(MethodInfo method, object[] args)
        => method.ReturnType.IsValueType ? Activator.CreateInstance(method.ReturnType) : null;
}
