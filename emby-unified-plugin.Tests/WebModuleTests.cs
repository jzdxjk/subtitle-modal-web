using System;
using System.IO;
using Emby.SubtitleAssistant.Web;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class WebModuleTests
{
    [Fact]
    public void LoaderIsIdempotentAndRemovalPreservesOtherPluginChanges()
    {
        var root = Path.Combine(Path.GetTempPath(), "subtitle-assistant-web-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var path = Path.Combine(root, "app.js");
            const string original = "otherPlugin();return Promise.all(list.map(loadPlugin));";
            File.WriteAllText(path, original);
            Assert.True(WebModuleInstaller.Install(root, "module-source"));
            var installed = File.ReadAllText(path);
            Assert.True(WebModuleInstaller.Install(root, "module-source"));
            Assert.Equal(installed, File.ReadAllText(path));
            File.AppendAllText(path, "laterPlugin();");
            WebModuleInstaller.Remove(root);
            Assert.Equal(original + "laterPlugin();", File.ReadAllText(path));
            Assert.Equal(original, File.ReadAllText(path + ".subtitleassistant.original.bak"));
            Assert.False(File.Exists(Path.Combine(root, "modules", "subtitleassistant-menu.js")));
        }
        finally { Directory.Delete(root, true); }
    }

    [Fact]
    public void UnknownLoaderDoesNotModifyServerJavascript()
    {
        var root = Path.Combine(Path.GetTempPath(), "subtitle-assistant-web-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var path = Path.Combine(root, "app.js");
            File.WriteAllText(path, "unknown loader");
            Assert.False(WebModuleInstaller.Install(root, "module-source"));
            Assert.Equal("unknown loader", File.ReadAllText(path));
        }
        finally { Directory.Delete(root, true); }
    }
}
