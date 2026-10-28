using Emby.SubtitleAssistant.Cloud;
using Emby.SubtitleAssistant.Web;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Net;
using MediaBrowser.Model.Users;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class CloudSecurityTests
{
    [Fact]
    public void AnonymousApiKeysAndRegularUsersAreNotAdministrators()
    {
        Assert.False(AdminAccess.IsAdministrator(null));
        Assert.False(AdminAccess.IsAdministrator(new AuthorizationInfo { Token = "api-key" }));
        Assert.False(AdminAccess.IsAdministrator(new AuthorizationInfo { User = new User { Policy = new UserPolicy() } }));
        Assert.True(AdminAccess.IsAdministrator(new AuthorizationInfo { User = new User { Policy = new UserPolicy { IsAdministrator = true } } }));
    }

    [Fact]
    public void JobViewCannotExposeBackendFailureBodyOrKnownCredentials()
    {
        var c = new PluginConfiguration { CloudApiToken = "cloud-secret", Proxy = new ProxyConfiguration { Password = "proxy-secret" } };
        var failed = CloudSafety.ForDisplay(new CloudJob
        {
            id = "1", status = "failed", message = "HTTP body cloud-secret, proxy-secret, https://server/path?token=unknown",
            display_title = "Title cloud-secret"
        }, c);
        Assert.DoesNotContain("secret", failed.Title);
        Assert.DoesNotContain("token=", failed.Message);
        Assert.DoesNotContain("HTTP body", failed.Message);
        var running = CloudSafety.ForDisplay(new CloudJob { status = "running", message = "cloud-secret at https://server/path?token=unknown" }, c);
        Assert.DoesNotContain("secret", running.Message);
        Assert.DoesNotContain("token=", running.Message);
    }

    [Theory]
    [InlineData("done", "pending", true)]
    [InlineData("done", "refreshing", true)]
    [InlineData("done", "success", false)]
    [InlineData("failed", "pending", false)]
    public void MonitorOnlyRefreshesCompletedPendingItems(string state, string refreshState, bool expected)
        => Assert.Equal(expected, CloudRefreshMonitor.ShouldRefresh(new CloudJob { id = "1", emby_item_id = "42", status = state, refresh_state = refreshState }));

    [Fact]
    public void RefreshCannotRecursivelyDownloadOrReplaceMetadata()
    {
        var options = CloudRefreshMonitor.CreateRefreshOptions(null);
        Assert.False(options.EnableSubtitleDownloading);
        Assert.False(options.ReplaceAllMetadata);
        Assert.False(options.ReplaceAllImages);
    }
}
