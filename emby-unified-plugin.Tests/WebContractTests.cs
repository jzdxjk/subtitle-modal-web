using System;
using System.IO;
using System.Linq;
using System.Reflection;
using MediaBrowser.Controller.Net;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class WebContractTests
{
    internal static string Root
    {
        get
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while (directory != null && !Directory.Exists(Path.Combine(directory.FullName, "emby-unified-plugin")))
                directory = directory.Parent;
            return directory?.FullName ?? throw new InvalidOperationException("Repository not found");
        }
    }

    [Fact]
    public void ConfigurationHasFiveAccessibleTabsAndNoIframe()
    {
        var path = Path.Combine(Root, "emby-unified-plugin", "Web", "configuration.html");
        Assert.True(File.Exists(path), "Unified configuration page is missing");
        var html = File.ReadAllText(path);
        foreach (var name in new[] { "local", "thunder", "pool", "cloud", "proxy" })
            Assert.Contains("data-tab=\"" + name + "\"", html);
        Assert.Contains("role=\"tablist\"", html);
        Assert.Contains("type=\"password\"", html);
        Assert.Contains("data-proxy-result", html);
        Assert.Contains("data-unsaved", html);
        Assert.Contains("全局设置", html);
        Assert.DoesNotContain("data-field=\"UpdateManifestUrl\"", html);
        Assert.DoesNotContain("data-field=\"PoolUrl\"", html);
        Assert.DoesNotContain("data-update", html);
        Assert.DoesNotContain("检查更新", html);
        Assert.Contains("完成搜索、匹配、去重与排序后，最多展示 N 条；不影响自动补全可用的候选。", html);
        Assert.DoesNotContain("data-field=\"SimplifiedChineseLanguage\"", html);
        Assert.DoesNotContain("data-field=\"TraditionalChineseLanguage\"", html);
        Assert.DoesNotContain("data-proxy-test-url", html);
        Assert.DoesNotContain("iframe", html, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void SettingsServiceRequiresAdministratorAuthentication()
    {
        var type = Assembly.Load("Emby.SubtitleAssistant").GetType("Emby.SubtitleAssistant.Web.SettingsService");
        Assert.NotNull(type);
        Assert.Equal("Admin", type.GetCustomAttribute<AuthenticatedAttribute>()?.Roles);
        Assert.DoesNotContain(type.GetCustomAttributes(), attribute => attribute.GetType().Name == "UnauthenticatedAttribute");
    }

    [Fact]
    public void MenuRequiresCurrentAdministratorAndUsesAuthenticatedApi()
    {
        var path = Path.Combine(Root, "emby-unified-plugin", "Web", "subtitleassistant-menu.js");
        Assert.True(File.Exists(path), "Cloud menu module is missing");
        var js = File.ReadAllText(path);
        Assert.Contains("IsAdministrator", js);
        Assert.Contains("getCurrentUserId", js);
        Assert.Contains("SubtitleAssistant/cloud/submit", js);
        Assert.DoesNotContain("responseText", js);
    }
}
