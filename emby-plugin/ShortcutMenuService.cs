using System;
using System.IO;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Text.Json;
using MediaBrowser.Controller.Net;
using MediaBrowser.Model.Services;

namespace SubtitleCloudPlugin;

[Unauthenticated]
public sealed class ShortcutMenuService : IService, IRequiresRequest
{
    private readonly IHttpResultFactory _results;
    private readonly HttpClient _http;
    public IRequest Request { get; set; }

    public ShortcutMenuService(IHttpResultFactory results, HttpClient http) { _results = results; _http = http; }

    public object Get(GetShortcutMenu request)
    {
        using var stream = typeof(ShortcutMenuService).GetTypeInfo().Assembly.GetManifestResourceStream("SubtitleCloudPlugin.shortcuts.js");
        using var reader = new StreamReader(stream ?? Stream.Null);
        var source = reader.ReadToEnd() + "\n" + Injection;
        return _results.GetResult(Request, source.AsSpan(), "application/x-javascript");
    }

    public async System.Threading.Tasks.Task<object> Post(SubmitSubtitleJob request)
    {
        if (request == null || string.IsNullOrWhiteSpace(request.InputPath) || request.Type == "Series" || request.Type == "Season")
            return new { ok = false, error = "仅支持电影和单集视频" };
        var cfg = Plugin.Instance.Configuration;
        var body = JsonSerializer.Serialize(new { input_path = PathMapping.Apply(request.InputPath, cfg.PathMappings), emby_item_id = request.ItemId ?? "", display_title = request.Name ?? "", av_code = request.AvCode ?? "", task_type = "native", formats = new[] { "srt" }, overwrite = false });
        using var msg = new HttpRequestMessage(HttpMethod.Post, cfg.ServiceUrl.TrimEnd('/') + "/api/plugin/jobs") { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        if (!string.IsNullOrWhiteSpace(cfg.ApiToken)) msg.Headers.Add("X-API-Token", cfg.ApiToken);
        using var response = await _http.SendAsync(msg).ConfigureAwait(false);
        var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
        return _results.GetResult(Request, text.AsSpan(), "application/json");
    }

    private const string Injection = @"
setTimeout(() => { Emby.importModule('./modules/common/globalize.js').then(globalize => {
const source={globalize,getCommands(options){const i=options.items?.[0];if(options.items?.length===1&&(i?.Type==='Movie'||i?.Type==='Episode'))return [{name:'生成云字幕',id:'subtitle_cloud',icon:'closed_caption'}];return []},executeCommand(command,items){if(command!=='subtitle_cloud')return;const i=items[0]||{};return fetch('/SubtitleCloud/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({InputPath:i.Path,ItemId:i.Id,Name:i.Name,Type:i.Type,AvCode:i.ProviderIds?.AV视频||''})}).then(r=>r.json()).then(x=>{if(x.ok===false)throw Error(x.error||'提交失败');globalize.translate('MessageSaved');})}};Emby.importModule('./modules/common/itemmanager/itemmanager.js').then(m=>m.registerCommandSource(source));});},3000);
";
}
