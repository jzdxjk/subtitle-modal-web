using System;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class NetworkTests
{
    [Fact] public void ProxyRoutingHonorsModuleAndBypassSettings()
    {
        var config = new PluginConfiguration();
        config.Proxy.Enabled = true;
        config.Proxy.Address = "http://proxy.example:7890";
        Assert.True(PluginHttpClient.ShouldProxy(config.Proxy, NetworkPurpose.Thunder, new Uri("https://api.example/x")));
        Assert.True(PluginHttpClient.ShouldProxy(config.Proxy, NetworkPurpose.Updates, new Uri("https://github.com/x")));
        Assert.False(PluginHttpClient.ShouldProxy(config.Proxy, NetworkPurpose.Cloud, new Uri("https://cloud.example/x")));
        foreach (var host in new[] { "127.0.0.1", "10.0.0.235", "192.168.31.1", "172.16.1.1", "[::1]", "[fd00::1234]", "nas" })
            Assert.False(PluginHttpClient.ShouldProxy(config.Proxy, NetworkPurpose.Thunder, new Uri("http://" + host + "/")));
        config.Proxy.BypassHosts = "*.internal.example; custom.example\nother.example";
        Assert.False(PluginHttpClient.ShouldProxy(config.Proxy, NetworkPurpose.Thunder, new Uri("https://api.internal.example/x")));
        Assert.False(PluginHttpClient.ShouldProxy(config.Proxy, NetworkPurpose.Thunder, new Uri("http://custom.example/")));
        Assert.True(PluginHttpClient.ShouldProxy(config.Proxy, NetworkPurpose.Thunder, new Uri("https://custom.example.attacker.net/")));
        config.Proxy.BypassLocal = false;
        Assert.True(PluginHttpClient.ShouldProxy(config.Proxy, NetworkPurpose.Thunder, new Uri("http://127.0.0.1/")));
    }

    [Fact] public async Task SendsHeadersAndBodyThroughSelectedPurpose()
    {
        var handler = new StubHandler(async (request, ct) =>
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("test-token", string.Join("", request.Headers.GetValues("X-API-Token")));
            Assert.Equal("{\"a\":1}", await request.Content.ReadAsStringAsync(ct));
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("{\"ok\":true}") };
        });
        NetworkPurpose? observed = null;
        using var http = new PluginHttpClient(() => new PluginConfiguration(), purpose => { observed = purpose; return handler; });
        var result = await http.SendJsonAsync("https://example.test/jobs", HttpMethod.Post, "{\"a\":1}", NetworkPurpose.Cloud,
            CancellationToken.None, new System.Collections.Generic.Dictionary<string,string> { ["X-API-Token"] = "test-token" });
        Assert.Equal("{\"ok\":true}", result);
        Assert.Equal(NetworkPurpose.Cloud, observed);
    }

    [Fact] public async Task FailureDoesNotRetryOrFallBackToDirect()
    {
        var config = new PluginConfiguration();
        config.Proxy.Enabled = true; config.Proxy.Address = "http://proxy.example:7890";
        var calls = 0;
        using var http = new PluginHttpClient(() => config, _ => new StubHandler((request, ct) =>
        { Interlocked.Increment(ref calls); throw new HttpRequestException("proxy unavailable"); }));
        await Assert.ThrowsAsync<HttpRequestException>(() => http.GetBytesAsync("https://example.test/sub", NetworkPurpose.Thunder, CancellationToken.None));
        Assert.Equal(1, calls);
    }

    [Fact] public async Task EnforcesByteLimitAndCancellation()
    {
        using var http = new PluginHttpClient(() => new PluginConfiguration(), _ => new StubHandler((r,ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(new byte[10]) })));
        await Assert.ThrowsAsync<HttpRequestException>(() => http.GetBytesAsync("https://example.test/sub", NetworkPurpose.Thunder, CancellationToken.None, maxBytes: 4));
        using var cts = new CancellationTokenSource();
        cts.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => http.GetBytesAsync("https://example.test/sub", NetworkPurpose.Thunder, cts.Token));
    }

    [Fact] public async Task ReusesClientUntilSettingsChange()
    {
        var config = new PluginConfiguration(); var created = 0;
        using var http = new PluginHttpClient(() => config, _ =>
        { created++; return new StubHandler((r,ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("ok") })); });
        await http.GetBytesAsync("https://example.test/a", NetworkPurpose.Thunder, CancellationToken.None);
        await http.GetBytesAsync("https://example.test/b", NetworkPurpose.Thunder, CancellationToken.None);
        Assert.Equal(1, created);
        config.Proxy.BypassHosts = "new.example";
        await http.GetBytesAsync("https://example.test/c", NetworkPurpose.Thunder, CancellationToken.None);
        Assert.Equal(2, created);
    }

    [Fact] public async Task CloudRedirectCannotForwardTokenToAnotherOrigin()
    {
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var first = new TcpListener(IPAddress.Loopback,0);
        var target = new TcpListener(IPAddress.Loopback,0);
        first.Start(); target.Start();
        var contacted = 0;
        async Task Serve(TcpListener listener, string response, bool observe)
        {
            try
            {
                using var socket = await listener.AcceptTcpClientAsync(stop.Token);
                using var stream = socket.GetStream();
                using var reader = new StreamReader(stream,Encoding.ASCII,false,1024,true);
                while (!string.IsNullOrEmpty(await reader.ReadLineAsync(stop.Token))) { }
                if (observe) Interlocked.Exchange(ref contacted,1);
                var bytes = Encoding.ASCII.GetBytes(response);
                await stream.WriteAsync(bytes,stop.Token);
            }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        }
        var targetPort = ((IPEndPoint)target.LocalEndpoint).Port;
        var firstPort = ((IPEndPoint)first.LocalEndpoint).Port;
        var firstServer = Serve(first,$"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{targetPort}/other\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",false);
        var targetServer = Serve(target,"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok",true);
        try
        {
            using var http = new PluginHttpClient(() => new PluginConfiguration(),null);
            await Assert.ThrowsAsync<HttpRequestException>(() => http.SendJsonAsync($"http://127.0.0.1:{firstPort}/jobs",HttpMethod.Get,null,
                NetworkPurpose.Cloud,stop.Token,new System.Collections.Generic.Dictionary<string,string> { ["X-API-Token"] = "dummy-test-token" }));
            Assert.Equal(0,Volatile.Read(ref contacted));
        }
        finally
        {
            stop.Cancel(); await Task.WhenAll(firstServer,targetServer); first.Stop(); target.Stop();
        }
    }

    private sealed class StubHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage,CancellationToken,Task<HttpResponseMessage>> _send;
        public StubHandler(Func<HttpRequestMessage,CancellationToken,Task<HttpResponseMessage>> send) => _send = send;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => _send(request,cancellationToken);
    }
}
