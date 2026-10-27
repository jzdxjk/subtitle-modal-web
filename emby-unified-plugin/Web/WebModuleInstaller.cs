using System;
using System.IO;
using System.Text;

namespace Emby.SubtitleAssistant.Web;

public static class WebModuleInstaller
{
    private const string Anchor = "Promise.all(list.map(loadPlugin))";
    private const string Injection = "/*subtitle-assistant:begin*/list.push(\"./modules/subtitleassistant-menu.js\"),/*subtitle-assistant:end*/";
    private static readonly object Gate = new object();

    public static bool Install(string uiPath, string moduleSource)
    {
        lock (Gate)
        {
            var path = Path.Combine(uiPath, "app.js");
            var source = File.ReadAllText(path);
            var installed = source.IndexOf(Injection, StringComparison.Ordinal) >= 0;
            var anchor = source.IndexOf(Anchor, StringComparison.Ordinal);
            if (!installed && (anchor < 0 || source.IndexOf("/*subtitle-assistant:begin*/", StringComparison.Ordinal) >= 0)) return false;
            var modulePath = Path.Combine(uiPath, "modules", "subtitleassistant-menu.js");
            Directory.CreateDirectory(Path.GetDirectoryName(modulePath));
            WriteAtomically(modulePath, moduleSource);
            if (!installed)
            {
                var backup = path + ".subtitleassistant.original.bak";
                if (!File.Exists(backup)) File.Copy(path, backup);
                WriteAtomically(path, source.Insert(anchor, Injection));
            }
            return true;
        }
    }

    public static void Remove(string uiPath)
    {
        lock (Gate)
        {
            var path = Path.Combine(uiPath, "app.js");
            if (File.Exists(path))
            {
                var source = File.ReadAllText(path);
                if (source.IndexOf(Injection, StringComparison.Ordinal) >= 0)
                    WriteAtomically(path, source.Replace(Injection, ""));
            }
            var module = Path.Combine(uiPath, "modules", "subtitleassistant-menu.js");
            if (File.Exists(module)) File.Delete(module);
        }
    }

    private static void WriteAtomically(string path, string content)
    {
        var temporary = path + ".subtitleassistant.tmp";
        try
        {
            File.WriteAllText(temporary, content, new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temporary, path, null);
            else File.Move(temporary, path);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
