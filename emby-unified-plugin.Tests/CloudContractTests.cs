using System.Reflection;
using MediaBrowser.Controller.Net;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class CloudContractTests
{
    [Fact]
    public void CloudServiceRequiresAdministratorAuthentication()
    {
        var type = Assembly.Load("Emby.SubtitleAssistant").GetType("Emby.SubtitleAssistant.Cloud.CloudAdminService");
        Assert.NotNull(type);
        Assert.Equal("Admin", type.GetCustomAttribute<AuthenticatedAttribute>()?.Roles);
    }
}
