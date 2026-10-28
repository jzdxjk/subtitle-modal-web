using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Text.RegularExpressions;
using MediaBrowser.Model.Serialization;

namespace Emby.SubtitleAssistant.Cloud;

public sealed class CloudJob
{
    public string id { get; set; }
    public string emby_item_id { get; set; }
    public string display_title { get; set; }
    public string status { get; set; }
    public string phase { get; set; }
    public double progress { get; set; }
    public string message { get; set; }
    public string refresh_state { get; set; }
    public double created_at { get; set; }
    public double updated_at { get; set; }
}

public sealed class CloudJobView
{
    public string Id { get; set; }
    public string Title { get; set; }
    public string Status { get; set; }
    public string Phase { get; set; }
    public double Progress { get; set; }
    public string Message { get; set; }
    public string RefreshState { get; set; }
    public double UpdatedAt { get; set; }
}

public static class CloudSafety
{
    public static CloudJobView ForDisplay(CloudJob job, PluginConfiguration configuration) => new CloudJobView
    {
        Id = Clean(job.id, configuration), Title = Clean(job.display_title, configuration),
        Status = Clean(job.status, configuration), Phase = Clean(job.phase, configuration),
        Progress = Math.Max(0, Math.Min(100, job.progress)), RefreshState = Clean(job.refresh_state, configuration),
        Message = job.status == "failed" ? "任务失败，请在字幕云服务查看详情。" : Clean(job.message, configuration),
        UpdatedAt = job.updated_at > 0 ? job.updated_at : job.created_at
    };

    private static string Clean(string value, PluginConfiguration configuration)
    {
        var text = value ?? "";
        foreach (var secret in new[] { configuration.CloudApiToken, configuration.Proxy?.Password })
            if (!string.IsNullOrEmpty(secret)) text = text.Replace(secret, "[已隐藏]");
        text = Regex.Replace(text, @"https?://\S+", "[链接已隐藏]", RegexOptions.IgnoreCase);
        return text.Length <= 300 ? text : text.Substring(0, 300);
    }
}

internal sealed class CloudApi
{
    private readonly IJsonSerializer _json;
    private readonly PluginHttpClient _http;
    internal CloudApi(IJsonSerializer json, PluginHttpClient http) { _json = json; _http = http; }

    private static string BaseUrl()
    {
        var value = Plugin.CurrentConfiguration.CloudServiceUrl;
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidOperationException("字幕云服务地址未配置。");
        return value.Trim().TrimEnd('/');
    }

    private static IDictionary<string, string> Headers()
    {
        var headers = new Dictionary<string, string>();
        var token = Plugin.CurrentConfiguration.CloudApiToken;
        if (!string.IsNullOrWhiteSpace(token)) headers["X-API-Token"] = token;
        return headers;
    }

    internal async Task<List<CloudJob>> JobsAsync(CancellationToken ct)
    {
        var text = await _http.SendJsonAsync(BaseUrl() + "/api/plugin/jobs", HttpMethod.Get, null,
            NetworkPurpose.Cloud, ct, Headers()).ConfigureAwait(false);
        return _json.DeserializeFromString<List<CloudJob>>(text) ?? new List<CloudJob>();
    }

    internal async Task<CloudJob> SubmitAsync(Dictionary<string, object> payload, CancellationToken ct)
    {
        var text = await _http.SendJsonAsync(BaseUrl() + "/api/plugin/jobs", HttpMethod.Post,
            _json.SerializeToString(payload), NetworkPurpose.Cloud, ct, Headers()).ConfigureAwait(false);
        return _json.DeserializeFromString<CloudJob>(text);
    }

    internal async Task ReportRefreshAsync(string id, string state, string message, CancellationToken ct)
        => await _http.SendJsonAsync(BaseUrl() + "/api/plugin/jobs/" + Uri.EscapeDataString(id) + "/refresh-result", HttpMethod.Post,
            _json.SerializeToString(new { state, message }), NetworkPurpose.Cloud, ct, Headers()).ConfigureAwait(false);
}
