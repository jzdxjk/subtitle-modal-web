using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Web;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Net;
using MediaBrowser.Model.Entities;
using MediaBrowser.Model.Serialization;
using MediaBrowser.Model.Services;

namespace Emby.SubtitleAssistant.Cloud;

[Route("/SubtitleAssistant/cloud/jobs", "GET")]
public sealed class GetCloudJobsRequest { }

[Route("/SubtitleAssistant/cloud/submit", "POST")]
public sealed class SubmitCloudJobRequest
{
    public string ItemId { get; set; }
    public string AvCode { get; set; }
    public string PosterUrl { get; set; }
}

public sealed class CloudResult
{
    public bool Ok { get; set; }
    public string Error { get; set; }
    public string Id { get; set; }
    public CloudJobView[] Jobs { get; set; }
}

[Authenticated(Roles = "Admin")]
public sealed class CloudAdminService : IService, IRequiresRequest
{
    private readonly IAuthorizationContext _authorization;
    private readonly ILibraryManager _library;
    private readonly CloudApi _api;
    public IRequest Request { get; set; }

    public CloudAdminService(IAuthorizationContext authorization, ILibraryManager library, IJsonSerializer json)
    {
        _authorization = authorization; _library = library; _api = new CloudApi(json, PluginHttpClient.Shared);
    }

    public async Task<object> Get(GetCloudJobsRequest request)
    {
        AdminAccess.Require(_authorization, Request);
        try
        {
            var jobs = await _api.JobsAsync(CancellationToken.None).ConfigureAwait(false);
            return new CloudResult { Ok = true, Jobs = jobs.Where(job => job != null)
                .Select(job => CloudSafety.ForDisplay(job, Plugin.CurrentConfiguration)).ToArray() };
        }
        catch { return new CloudResult { Ok = false, Error = "无法获取字幕云任务，请检查服务连接和 API Token。" }; }
    }

    public async Task<object> Post(SubmitCloudJobRequest request)
    {
        AdminAccess.Require(_authorization, Request);
        if (!long.TryParse(request?.ItemId, out var id)) return new CloudResult { Ok = false, Error = "无效的媒体项目。" };
        try
        {
            var item = _library.GetItemById(id);
            if (item == null || !(item.GetType().Name == "Movie" || item.GetType().Name == "Episode"))
                return new CloudResult { Ok = false, Error = "仅支持电影和单集视频。" };
            var source = item.GetMediaSources(true, false, null).FirstOrDefault();
            var path = !string.IsNullOrWhiteSpace(item.Path) ? item.Path : source?.Path;
            var audio = source?.MediaStreams?.Where(stream => stream.Type == MediaStreamType.Audio)
                .OrderByDescending(stream => stream.IsDefault).ThenBy(stream => stream.Index).FirstOrDefault();
            var media = new CloudMediaInfo
            {
                ItemId = request.ItemId, Path = path, Title = item.Name, Type = item.GetType().Name,
                AvCode = request.AvCode, PosterUrl = request.PosterUrl
            };
            if (path?.EndsWith(".strm", StringComparison.OrdinalIgnoreCase) == true && File.Exists(path))
                media.StrmContent = string.Join("\n", File.ReadLines(path).Take(32));
            if (audio != null && audio.BitRate > 0 && audio.Channels > 0)
                media.Audio = new CloudAudioInfo
                {
                    Index = audio.Index, Codec = audio.Codec, Channels = audio.Channels.GetValueOrDefault(),
                    BitRate = audio.BitRate.GetValueOrDefault(), SampleRate = audio.SampleRate.GetValueOrDefault()
                };
            var result = await _api.SubmitAsync(CloudPayload.Create(media, Plugin.CurrentConfiguration.CloudPathMappings),
                CancellationToken.None).ConfigureAwait(false);
            return new CloudResult { Ok = true, Id = result?.id };
        }
        catch { return new CloudResult { Ok = false, Error = "云字幕任务提交失败，请检查服务配置和媒体路径映射。" }; }
    }
}
