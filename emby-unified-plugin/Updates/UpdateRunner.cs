using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Model.Serialization;

namespace Emby.SubtitleAssistant.Updates;

internal sealed class UpdateRunner
{
    private static readonly SemaphoreSlim Gate = new SemaphoreSlim(1, 1);
    private readonly PluginHttpClient _http;
    private readonly IJsonSerializer _json;
    internal UpdateRunner(PluginHttpClient http, IJsonSerializer json) { _http = http; _json = json; }

    internal async Task<UpdateInstallResult> RunAsync(string manifestUrl, Version serverVersion, string destination,
        Version runningVersion, CancellationToken ct, IProgress<double> progress)
    {
        await Gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            progress?.Report(0);
            var bytes = await _http.GetBytesAsync(manifestUrl, NetworkPurpose.Updates, ct, maxBytes: 65536).ConfigureAwait(false);
            var manifest = _json.DeserializeFromString<UpdateManifest>(Encoding.UTF8.GetString(bytes).TrimStart('\ufeff'))
                ?? throw new InvalidDataException("更新清单为空。");
            progress?.Report(25);
            var target = manifest.Validate(serverVersion);
            var current = PackageInstaller.ReadIdentity(destination);
            if (current.Name != "Emby.SubtitleAssistant") throw new InvalidDataException("当前插件文件身份不匹配。");
            if (runningVersion >= target || current.Version >= target)
            { progress?.Report(100); return new UpdateInstallResult(); }
            ct.ThrowIfCancellationRequested();
            var package = await _http.GetBytesAsync(manifest.download_url, NetworkPurpose.Updates, ct,
                timeoutSeconds: 60, maxBytes: 64 * 1024 * 1024).ConfigureAwait(false);
            progress?.Report(75);
            var result = PackageInstaller.Install(package, manifest, destination, runningVersion, ct);
            progress?.Report(100);
            return result;
        }
        finally { Gate.Release(); }
    }
}
