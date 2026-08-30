using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using MediaBrowser.Model.Serialization;

namespace SubtitleCloudPlugin;

public sealed class SubtitleCloudApi
{
    private readonly HttpClient _http;
    private readonly PluginConfiguration _config;
    private readonly IJsonSerializer _json;
    public SubtitleCloudApi(HttpClient http, PluginConfiguration config, IJsonSerializer json) { _http = http; _config = config; _json = json; }

    public async Task<string> CreateJobAsync(object payload)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, _config.ServiceUrl.TrimEnd('/') + "/api/plugin/jobs");
        if (!string.IsNullOrWhiteSpace(_config.ApiToken)) request.Headers.Add("X-API-Token", _config.ApiToken);
        request.Content = new StringContent(_json.SerializeToString(payload), Encoding.UTF8, "application/json");
        using var response = await _http.SendAsync(request).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync().ConfigureAwait(false);
    }

    public async Task<string> ListJobsAsync()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, _config.ServiceUrl.TrimEnd('/') + "/api/plugin/jobs");
        AddToken(request);
        using var response = await _http.SendAsync(request).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync().ConfigureAwait(false);
    }

    public async Task SetRefreshResultAsync(string jobId, string state, string message)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, _config.ServiceUrl.TrimEnd('/') + "/api/plugin/jobs/" + jobId + "/refresh-result");
        AddToken(request);
        request.Content = new StringContent(_json.SerializeToString(new { state, message }), Encoding.UTF8, "application/json");
        using var response = await _http.SendAsync(request).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
    }

    private void AddToken(HttpRequestMessage request)
    {
        if (!string.IsNullOrWhiteSpace(_config.ApiToken)) request.Headers.Add("X-API-Token", _config.ApiToken);
    }
}
