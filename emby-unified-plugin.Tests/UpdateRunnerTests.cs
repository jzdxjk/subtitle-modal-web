using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Updates;
using MediaBrowser.Model.Serialization;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class UpdateRunnerTests
{
    [Fact]
    public async Task ConcurrentUpdatesUseUpdateNetworkPurposeAndInstallOnlyOnce()
    {
        var root = Path.Combine(Path.GetTempPath(), "subtitle-assistant-runner-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var original = File.ReadAllBytes(typeof(Plugin).Assembly.Location);
            var candidate = UpdateInstallerTests.WithVersion(original, new Version(1, 0, 0, 1));
            var path = Path.Combine(root, "Emby.SubtitleAssistant.dll"); File.WriteAllBytes(path, original);
            var manifest = UpdateManifestTests.Manifest(); manifest.sha256 = UpdateInstallerTests.Hash(candidate);
            var handler = new UpdateHandler(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(manifest)), candidate);
            using var http = new PluginHttpClient(() => new PluginConfiguration(), purpose => { Assert.Equal(NetworkPurpose.Updates, purpose); return handler; });
            var runner = new UpdateRunner(http, DispatchProxy.Create<IJsonSerializer, UpdateJsonProxy>());
            var progress = new CapturedProgress();
            var first = runner.RunAsync("https://release.invalid/update.json", new Version(4, 9, 5, 0), path, new Version(1, 0, 0, 0), CancellationToken.None, progress);
            var second = runner.RunAsync("https://release.invalid/update.json", new Version(4, 9, 5, 0), path, new Version(1, 0, 0, 0), CancellationToken.None, progress);
            var results = await Task.WhenAll(first, second);
            Assert.Single(results, result => result.Installed);
            Assert.Equal(2, handler.ManifestRequests);
            Assert.Equal(1, handler.PackageRequests);
            Assert.Equal(1, handler.MaximumActiveRequests);
            Assert.Contains(100, progress.Values);
            Assert.Equal(candidate, File.ReadAllBytes(path));
        }
        finally { Directory.Delete(root, true); }
    }

    [Fact]
    public async Task IncompatibleManifestNeverDownloadsPackageOrChangesDisk()
    {
        var root = Path.Combine(Path.GetTempPath(), "subtitle-assistant-runner-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var original = File.ReadAllBytes(typeof(Plugin).Assembly.Location);
            var path = Path.Combine(root, "Emby.SubtitleAssistant.dll"); File.WriteAllBytes(path, original);
            var handler = new UpdateHandler(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(UpdateManifestTests.Manifest())), new byte[] { 0 });
            using var http = new PluginHttpClient(() => new PluginConfiguration(), _ => handler);
            var runner = new UpdateRunner(http, DispatchProxy.Create<IJsonSerializer, UpdateJsonProxy>());
            await Assert.ThrowsAsync<InvalidDataException>(() => runner.RunAsync("https://release.invalid/update.json", new Version(4, 11, 0, 0), path,
                new Version(1, 0, 0, 0), CancellationToken.None, null));
            Assert.Equal(0, handler.PackageRequests);
            Assert.Equal(original, File.ReadAllBytes(path));
        }
        finally { Directory.Delete(root, true); }
    }

    private sealed class CapturedProgress : IProgress<double>
    {
        public ConcurrentBag<double> Values { get; } = new ConcurrentBag<double>();
        public void Report(double value) => Values.Add(value);
    }

    private sealed class UpdateHandler : HttpMessageHandler
    {
        private readonly byte[] _manifest, _package;
        private int _active;
        public int ManifestRequests, PackageRequests, MaximumActiveRequests;
        public UpdateHandler(byte[] manifest, byte[] package) { _manifest = manifest; _package = package; }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var active = Interlocked.Increment(ref _active);
            MaximumActiveRequests = Math.Max(MaximumActiveRequests, active);
            try
            {
                await Task.Delay(15, cancellationToken);
                var manifest = request.RequestUri.AbsolutePath.EndsWith(".json", StringComparison.Ordinal);
                if (manifest) Interlocked.Increment(ref ManifestRequests); else Interlocked.Increment(ref PackageRequests);
                return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(manifest ? _manifest : _package) };
            }
            finally { Interlocked.Decrement(ref _active); }
        }
    }
}

public class UpdateJsonProxy : DispatchProxy
{
    protected override object Invoke(MethodInfo method, object[] args)
    {
        if (method.Name == "DeserializeFromString") return JsonSerializer.Deserialize((string)args[0], method.GetGenericArguments()[0]);
        if (method.Name == "SerializeToString") return JsonSerializer.Serialize(args[0]);
        throw new NotSupportedException(method.Name);
    }
}
