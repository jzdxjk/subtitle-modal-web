using MediaBrowser.Controller.Net;
using MediaBrowser.Model.Services;

namespace SubtitleCloudPlugin;

[Route("/SubtitleCloud/submit", "POST", IsHidden = true)]
public sealed class SubmitSubtitleJob
{
    public string InputPath { get; set; }
    public string ItemId { get; set; }
    public string Name { get; set; }
    public string Type { get; set; }
    public string AvCode { get; set; }
    public string PosterUrl { get; set; }
}

[Route("/SubtitleCloud/dashboard", "GET", IsHidden = true)]
public sealed class GetSubtitleCloudDashboard { }
[Route("/SubtitleCloud/jobs", "GET", IsHidden = true)]
public sealed class GetSubtitleCloudJobs { }
[Route("/SubtitleCloud/settings", "POST", IsHidden = true)]
public sealed class SaveSubtitleCloudSettings { public string ServiceUrl { get; set; } public string ApiToken { get; set; } public string PathMappings { get; set; } }
