using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Net;
using System.Threading;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Net;
using MediaBrowser.Common.Net;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Services;
using MediaBrowser.Model.Serialization;

namespace SubtitleCloudPlugin;

[Unauthenticated]
public sealed class ShortcutMenuService : IService, IRequiresRequest
{
    private readonly IHttpResultFactory _results;
    private readonly IHttpClient _http;
    private readonly IJsonSerializer _json;
    private readonly ILibraryManager _libraryManager;
    private readonly ILogger _logger;
    public IRequest Request { get; set; }

    public ShortcutMenuService(IHttpResultFactory results, IHttpClient http, IJsonSerializer json, ILibraryManager libraryManager, ILogManager logManager)
    {
        _results = results;
        _http = http;
        _json = json;
        _libraryManager = libraryManager;
        _logger = logManager.GetLogger(nameof(ShortcutMenuService));
    }

    public object Get(GetSubtitleCloudDashboard request)
    {
        using var stream = typeof(ShortcutMenuService).Assembly.GetManifestResourceStream("SubtitleCloudPlugin.Dashboard.html");
        using var reader = new StreamReader(stream ?? Stream.Null);
        var c = Plugin.Instance.Configuration;
        var html = reader.ReadToEnd().Replace("{{SERVICE_URL}}", WebUtility.HtmlEncode(c.ServiceUrl ?? "")).Replace("{{API_TOKEN}}", WebUtility.HtmlEncode(c.ApiToken ?? "")).Replace("{{PATH_MAPPINGS}}", WebUtility.HtmlEncode(c.PathMappings ?? "")).Replace("{{NOTICE}}", "");
        return _results.GetResult(Request, html.AsSpan(), "text/html; charset=utf-8");
    }

    public async System.Threading.Tasks.Task<object> Get(GetSubtitleCloudJobs request)
    {
        var c = Plugin.Instance.Configuration;
        var url = (string.IsNullOrWhiteSpace(c.ServiceUrl) ? "http://10.0.0.235:9198" : c.ServiceUrl).TrimEnd('/') + "/api/plugin/jobs";
        var o = new HttpRequestOptions { Url = url, AcceptHeader = "application/json", CancellationToken = CancellationToken.None, BufferContent = true };
        if (!string.IsNullOrWhiteSpace(c.ApiToken)) o.RequestHeaders["X-API-Token"] = c.ApiToken;
        using var response = await _http.SendAsync(o, "GET").ConfigureAwait(false); using var reader = new StreamReader(response.Content); var text = await reader.ReadToEndAsync().ConfigureAwait(false);
        return _results.GetResult(Request, text.AsSpan(), "application/json");
    }

    public object Post(SaveSubtitleCloudSettings request)
    {
        Plugin.Instance.Configuration.ServiceUrl = request?.ServiceUrl ?? ""; Plugin.Instance.Configuration.ApiToken = request?.ApiToken ?? ""; Plugin.Instance.Configuration.PathMappings = request?.PathMappings ?? ""; Plugin.Instance.SaveConfiguration();
        return Get(new GetSubtitleCloudDashboard());
    }

    public async System.Threading.Tasks.Task<object> Post(SubmitSubtitleJob request)
    {
        if (request == null || request.Type == "Series" || request.Type == "Season")
            return new { ok = false, error = "仅支持电影和单集视频" };
        var inputPath = request.InputPath;
        var taskType = "native";
        if (long.TryParse(request.ItemId, out var itemId))
        {
            var item = _libraryManager.GetItemById(itemId);
            if (!string.IsNullOrWhiteSpace(item?.Path))
            {
                inputPath = item.Path;
                if (item.Path.EndsWith(".strm", StringComparison.OrdinalIgnoreCase) && File.Exists(item.Path))
                {
                    var strmSource = File.ReadLines(item.Path)
                        .Select(line => line.Trim())
                        .FirstOrDefault(line => line.Length > 0 && !line.StartsWith("#"));
                    if (!string.IsNullOrWhiteSpace(strmSource))
                        taskType = strmSource.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
                            || strmSource.StartsWith("https://", StringComparison.OrdinalIgnoreCase)
                            ? "strm-http"
                            : "strm-local";
                }
            }
            else
            {
                var mediaSource = item?.GetMediaSources(true, false, null).FirstOrDefault();
                if (!string.IsNullOrWhiteSpace(mediaSource?.Path)) inputPath = mediaSource.Path;
            }
        }
        if (string.IsNullOrWhiteSpace(inputPath))
            return new { ok = false, error = "未找到媒体路径" };
        _logger.Info("SubtitleCloud submit: ItemId=" + request.ItemId + ", Path=" + inputPath);
        var cfg = Plugin.Instance.Configuration;
        var mappedPath = PathMapping.Apply(inputPath, cfg.PathMappings);
        var body = _json.SerializeToString(new
        {
            input_path = mappedPath,
            emby_item_id = request.ItemId ?? "",
            display_title = request.Name ?? "",
            av_code = request.AvCode ?? "",
            poster_url = request.PosterUrl ?? "",
            task_type = taskType,
            formats = new[] { "srt" },
            overwrite = false
        });
        var serviceUrl = cfg.ServiceUrl;
        if (string.IsNullOrWhiteSpace(serviceUrl))
            serviceUrl = "http://10.0.0.235:9198";
        var options = new HttpRequestOptions
        {
            Url = serviceUrl.TrimEnd('/') + "/api/plugin/jobs",
            RequestContent = body.AsMemory(),
            RequestContentType = "application/json",
            AcceptHeader = "application/json",
            CancellationToken = CancellationToken.None,
            BufferContent = true
        };
        if (!string.IsNullOrWhiteSpace(cfg.ApiToken)) options.RequestHeaders["X-API-Token"] = cfg.ApiToken;
        using var response = await _http.SendAsync(options, "POST").ConfigureAwait(false);
        using var responseReader = new StreamReader(response.Content);
        var text = await responseReader.ReadToEndAsync().ConfigureAwait(false);
        var statusCode = (int)response.StatusCode;
        if (statusCode < 200 || statusCode > 299)
        {
            var error = _json.SerializeToString(new
            {
                ok = false,
                error = "字幕服务返回 " + statusCode + ": " + text
            });
            return _results.GetResult(Request, error.AsSpan(), "application/json");
        }
        return _results.GetResult(Request, text.AsSpan(), "application/json");
    }

}
