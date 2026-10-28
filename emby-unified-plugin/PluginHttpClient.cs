using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Emby.SubtitleAssistant;

public enum NetworkPurpose { Thunder, Cloud, Updates }

public sealed class PluginHttpClient : IDisposable
{
    public static PluginHttpClient Shared { get; } = new PluginHttpClient();
    private readonly Func<PluginConfiguration> _configuration;
    private readonly Func<NetworkPurpose, HttpMessageHandler> _handlerFactory;
    private readonly Dictionary<NetworkPurpose, ClientEntry> _clients = new Dictionary<NetworkPurpose, ClientEntry>();
    private readonly object _gate = new object();
    private bool _disposed;

    public PluginHttpClient() : this(() => Plugin.CurrentConfiguration, null) { }
    internal PluginHttpClient(Func<PluginConfiguration> configuration, Func<NetworkPurpose, HttpMessageHandler> handlerFactory)
    { _configuration = configuration; _handlerFactory = handlerFactory; }

    public static bool ShouldProxy(ProxyConfiguration proxy, NetworkPurpose purpose, Uri target) =>
        ModuleUsesProxy(proxy, purpose) && !IsBypassed(proxy, target);

    public async Task<byte[]> GetBytesAsync(string url, NetworkPurpose purpose, CancellationToken ct,
        int timeoutSeconds = 30, int maxBytes = 16777216)
    {
        using var request = CreateRequest(url, HttpMethod.Get, null, null);
        return await SendBytesAsync(request, purpose, ct, timeoutSeconds, maxBytes).ConfigureAwait(false);
    }

    public async Task<string> SendJsonAsync(string url, HttpMethod method, string body, NetworkPurpose purpose,
        CancellationToken ct, IDictionary<string,string> headers = null, int timeoutSeconds = 30)
    {
        using var request = CreateRequest(url, method, body, headers);
        var bytes = await SendBytesAsync(request, purpose, ct, timeoutSeconds, 16777216).ConfigureAwait(false);
        return Encoding.UTF8.GetString(bytes);
    }

    private static HttpRequestMessage CreateRequest(string url, HttpMethod method, string body, IDictionary<string,string> headers)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || (uri.Scheme != "http" && uri.Scheme != "https") ||
            !string.IsNullOrEmpty(uri.UserInfo)) throw new ArgumentException("请求地址必须为无内嵌凭据的HTTP或HTTPS地址。");
        var request = new HttpRequestMessage(method, uri);
        request.Headers.TryAddWithoutValidation("User-Agent", "Emby.SubtitleAssistant/1.0");
        if (body != null) request.Content = new StringContent(body, Encoding.UTF8, "application/json");
        if (headers != null)
            foreach (var header in headers)
                if (!request.Headers.TryAddWithoutValidation(header.Key, header.Value))
                    throw new ArgumentException("无效请求头。");
        return request;
    }

    private async Task<byte[]> SendBytesAsync(HttpRequestMessage request, NetworkPurpose purpose, CancellationToken ct, int timeoutSeconds, int maxBytes)
    {
        if (timeoutSeconds <= 0 || maxBytes <= 0) throw new ArgumentOutOfRangeException();
        ct.ThrowIfCancellationRequested();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));
        var entry = Acquire(purpose);
        try
        {
            using var response = await entry.Client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token).ConfigureAwait(false);
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength > maxBytes) throw new HttpRequestException("响应超过允许大小。");
            using var stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false);
            using var buffer = new MemoryStream();
            var chunk = new byte[81920];
            int length;
            while ((length = await stream.ReadAsync(chunk, 0, chunk.Length, timeout.Token).ConfigureAwait(false)) != 0)
            {
                if (buffer.Length + length > maxBytes) throw new HttpRequestException("响应超过允许大小。");
                buffer.Write(chunk, 0, length);
            }
            return buffer.ToArray();
        }
        finally { Release(entry); }
    }

    private ClientEntry Acquire(NetworkPurpose purpose)
    {
        var proxy = _configuration()?.Proxy ?? new ProxyConfiguration();
        var fingerprint = Fingerprint(proxy);
        lock (_gate)
        {
            if (_disposed) throw new ObjectDisposedException(nameof(PluginHttpClient));
            if (!_clients.TryGetValue(purpose, out var entry) || entry.Fingerprint != fingerprint)
            {
                if (entry != null) { entry.Retired = true; if (entry.Users == 0) entry.Client.Dispose(); }
                HttpMessageHandler handler;
                if (_handlerFactory != null) handler = _handlerFactory(purpose);
                else
                {
                    var useProxy = ModuleUsesProxy(proxy, purpose);
                    handler = new HttpClientHandler
                    {
                        UseProxy = useProxy,
                        Proxy = useProxy ? new RoutingProxy(proxy) : null,
                        AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
                        // HttpClient forwards custom token headers on redirects; cloud endpoints must use their final URL.
                        AllowAutoRedirect = purpose != NetworkPurpose.Cloud,
                        MaxAutomaticRedirections = 5
                    };
                }
                entry = new ClientEntry { Fingerprint = fingerprint,
                    Client = new HttpClient(handler, true) { Timeout = Timeout.InfiniteTimeSpan } };
                _clients[purpose] = entry;
            }
            entry.Users++;
            return entry;
        }
    }

    private void Release(ClientEntry entry)
    {
        lock (_gate) { entry.Users--; if (entry.Users == 0 && entry.Retired) entry.Client.Dispose(); }
    }

    private static bool ModuleUsesProxy(ProxyConfiguration proxy, NetworkPurpose purpose)
    {
        if (proxy == null || !proxy.Enabled) return false;
        switch (purpose)
        {
            case NetworkPurpose.Thunder: return proxy.Thunder;
            case NetworkPurpose.Cloud: return proxy.Cloud;
            case NetworkPurpose.Updates: return proxy.Updates;
            default: return false;
        }
    }

    private static bool IsBypassed(ProxyConfiguration proxy, Uri target)
    {
        var host = target.DnsSafeHost.Trim('[', ']');
        if (proxy.BypassLocal)
        {
            if (target.IsLoopback || (host.IndexOf('.') < 0 && host.IndexOf(':') < 0)) return true;
            if (IPAddress.TryParse(host, out var ip))
            {
                if (ip.IsIPv4MappedToIPv6) ip = ip.MapToIPv4();
                var bytes = ip.GetAddressBytes();
                if (IPAddress.IsLoopback(ip) || (bytes.Length == 4 && (bytes[0] == 10 || bytes[0] == 127 || bytes[0] == 0 ||
                    (bytes[0] == 192 && bytes[1] == 168) || (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
                    (bytes[0] == 169 && bytes[1] == 254))) ||
                    (bytes.Length == 16 && ((bytes[0] & 0xfe) == 0xfc || (bytes[0] == 0xfe && (bytes[1] & 0xc0) == 0x80)))) return true;
            }
        }
        foreach (var pattern in (proxy.BypassHosts ?? "").Split(new[] { ';', ',', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
        {
            var value = pattern.Trim();
            if (value.Length == 0 || value.Length > 255) continue;
            var expression = "^" + Regex.Escape(value).Replace("\\*", ".*") + "$";
            try { if (Regex.IsMatch(host, expression, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(100))) return true; }
            catch (RegexMatchTimeoutException) { }
        }
        return false;
    }

    private static string Fingerprint(ProxyConfiguration proxy)
    {
        // Only retain a digest as a cache key; proxy credentials must never enter diagnostics.
        var value = string.Join("\n", proxy.Enabled, proxy.Address, proxy.Username, proxy.Password, proxy.BypassLocal,
            proxy.BypassHosts, proxy.Thunder, proxy.Cloud, proxy.Updates);
        using var hash = SHA256.Create();
        return Convert.ToBase64String(hash.ComputeHash(Encoding.UTF8.GetBytes(value)));
    }

    public void Dispose()
    {
        lock (_gate)
        {
            _disposed = true;
            foreach (var entry in _clients.Values) { entry.Retired = true; if (entry.Users == 0) entry.Client.Dispose(); }
            _clients.Clear();
        }
    }

    private sealed class ClientEntry
    { public string Fingerprint; public HttpClient Client; public int Users; public bool Retired; }

    private sealed class RoutingProxy : IWebProxy
    {
        private readonly ProxyConfiguration _settings;
        private readonly Uri _address;
        public RoutingProxy(ProxyConfiguration settings)
        {
            _address = settings.ValidateAddress();
            _settings = new ProxyConfiguration { BypassLocal = settings.BypassLocal, BypassHosts = settings.BypassHosts };
            Credentials = string.IsNullOrEmpty(settings.Username) ? null : new NetworkCredential(settings.Username, settings.Password);
        }
        public ICredentials Credentials { get; set; }
        public Uri GetProxy(Uri destination) => IsBypassed(destination) ? destination : _address;
        public bool IsBypassed(Uri host) => PluginHttpClient.IsBypassed(_settings, host);
    }
}
