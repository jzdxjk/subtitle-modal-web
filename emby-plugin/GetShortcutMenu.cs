using MediaBrowser.Controller.Net;
using MediaBrowser.Model.Services;

namespace SubtitleCloudPlugin;

[Route("/{Web}/modules/shortcuts.js", "GET", IsHidden = true)]
[Unauthenticated]
public sealed class GetShortcutMenu { public string Web { get; set; } }

[Route("/SubtitleCloud/submit", "POST", IsHidden = true)]
public sealed class SubmitSubtitleJob
{
    public string InputPath { get; set; }
    public string ItemId { get; set; }
    public string Name { get; set; }
    public string Type { get; set; }
    public string AvCode { get; set; }
}
