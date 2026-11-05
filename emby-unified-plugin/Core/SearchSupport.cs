using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Controller.Subtitles;
using MediaBrowser.Model.Providers;
namespace Emby.SubtitleAssistant.Core
{
    public sealed class SubtitleCandidate
    {
        public string Name { get; set; }
        public double? DurationSeconds { get; set; }
        public string DurationSource { get; set; }
        public long? SizeBytes { get; set; }
        public int StableOrder { get; set; }
        public string Id { get; set; }
        public string Format { get; set; }
        public string Language { get; set; }
        public string DownloadUrl { get; set; }
        public string ContentHash { get; set; }
        public bool IsChickenRice { get; set; }
    }
    public static class SubtitleRanking
    {
        public static IReadOnlyList<SubtitleCandidate> Order(IEnumerable<SubtitleCandidate> candidates, double? runtime, bool chickenRiceFirst = false)
        {
            IOrderedEnumerable<SubtitleCandidate> ordered = chickenRiceFirst
                ? candidates.OrderByDescending(x => x.IsChickenRice)
                : candidates.OrderBy(_ => 0);
            return ordered.ThenBy(x => runtime > 0 ? x.DurationSeconds > 0 ? Math.Abs(x.DurationSeconds.Value - runtime.Value) : double.MaxValue : 0)
                .ThenByDescending(x => x.SizeBytes.HasValue).ThenByDescending(x => x.SizeBytes ?? 0).ThenBy(x => x.StableOrder).ToArray();
        }
    }
    public static class SearchExecutionContext
    {
        private static readonly AsyncLocal<bool> Automation = new AsyncLocal<bool>();
        public static bool IsAutomation => Automation.Value;
        public static IDisposable BeginAutomation()
        {
            var scope = new Scope(Automation.Value);
            Automation.Value = true;
            return scope;
        }
        private sealed class Scope : IDisposable
        {
            private readonly bool _previous;
            private bool _disposed;
            public Scope(bool previous) { _previous = previous; }
            public void Dispose() { if (!_disposed) { Automation.Value = _previous; _disposed = true; } }
        }
    }
    public sealed class SubtitleBodyCache
    {
        private readonly object _gate = new object();
        private readonly Dictionary<string, Entry> _entries = new Dictionary<string, Entry>(StringComparer.Ordinal);
        private readonly long _maxBytes;
        private readonly TimeSpan _ttl;
        private readonly Func<DateTimeOffset> _clock;
        private long _total;
        private long _access;
        public SubtitleBodyCache(long maxBytes = 134217728, TimeSpan? ttl = null, Func<DateTimeOffset> clock = null)
        { _maxBytes = maxBytes; _ttl = ttl ?? TimeSpan.FromHours(24); _clock = clock ?? (() => DateTimeOffset.UtcNow); }
        public long TotalBytes { get { lock (_gate) { RemoveExpired(); return _total; } } }
        public void Put(string key, byte[] bytes)
        {
            lock (_gate)
            {
                RemoveExpired();
                if (_entries.TryGetValue(key, out var old)) Remove(key, old);
                if (bytes == null || bytes.LongLength > _maxBytes) return;
                while (_total + bytes.LongLength > _maxBytes && _entries.Count != 0)
                {
                    var oldest = _entries.OrderBy(x => x.Value.Accessed).First();
                    Remove(oldest.Key, oldest.Value);
                }
                _entries[key] = new Entry { Bytes = bytes, Expires = _clock() + _ttl, Accessed = ++_access };
                _total += bytes.LongLength;
            }
        }
        public bool TryGet(string key, out byte[] bytes)
        {
            lock (_gate)
            {
                RemoveExpired();
                if (key != null && _entries.TryGetValue(key, out var entry)) { entry.Accessed = ++_access; bytes = entry.Bytes; return true; }
                bytes = null;
                return false;
            }
        }
        private void RemoveExpired() { foreach (var row in _entries.Where(x => x.Value.Expires <= _clock()).ToArray()) Remove(row.Key, row.Value); }
        private void Remove(string key, Entry entry) { _entries.Remove(key); _total -= entry.Bytes.LongLength; }
        private sealed class Entry { public byte[] Bytes; public DateTimeOffset Expires; public long Accessed; }
    }

    // Collapses concurrent and near-term identical source searches across host searches and scheduled tasks.
    // The shared work is detached from any single caller so one cancelled caller cannot cancel the others.
    public sealed class ProviderSearchCache
    {
        internal static ProviderSearchCache Shared = new ProviderSearchCache();
        private readonly object _gate = new object();
        private readonly Dictionary<string, Entry> _entries = new Dictionary<string, Entry>(StringComparer.Ordinal);
        private readonly int _capacity;
        private readonly TimeSpan _ttl;
        private readonly Func<DateTimeOffset> _clock;
        private long _access;

        public ProviderSearchCache(int capacity = 256, TimeSpan? ttl = null, Func<DateTimeOffset> clock = null)
        {
            _capacity = Math.Max(1, capacity);
            _ttl = ttl ?? TimeSpan.FromSeconds(60);
            _clock = clock ?? (() => DateTimeOffset.UtcNow);
        }

        public static string Key(string provider, SubtitleSearchRequest request, string configuration)
        {
            var identifier = MediaIdentifier.TryParse(request?.MediaPath);
            var codes = identifier == null ? "" : string.Join(",", identifier.QueryVariants.OrderBy(x => x, StringComparer.Ordinal));
            return string.Join("|", new[]
            {
                provider ?? "",
                (request?.MediaPath ?? "").Replace('\\', '/'),
                codes,
                request?.Language ?? "",
                request?.IsPerfectMatch == true ? "perfect" : "",
                request?.IsForced == true ? "forced" : "",
                request?.IsHearingImpaired == true ? "hi" : "",
                SearchExecutionContext.IsAutomation ? "automation" : "display",
                configuration ?? ""
            });
        }

        public async Task<RemoteSubtitleInfo[]> GetOrCreateAsync(string key,
            Func<CancellationToken,Task<IEnumerable<RemoteSubtitleInfo>>> factory, CancellationToken cancellationToken)
        {
            if (string.IsNullOrEmpty(key)) throw new ArgumentException("A cache key is required.", nameof(key));
            if (factory == null) throw new ArgumentNullException(nameof(factory));
            Task<RemoteSubtitleInfo[]> shared;
            lock (_gate)
            {
                RemoveExpired();
                if (_entries.TryGetValue(key, out var existing))
                {
                    existing.Accessed = ++_access;
                    shared = existing.Task;
                }
                else
                {
                    EnsureCapacity();
                    var entry = new Entry { Accessed = ++_access };
                    _entries[key] = entry;
                    entry.Task = PopulateAsync(key, entry, factory);
                    shared = entry.Task;
                }
            }
            return await ObserveAsync(shared, cancellationToken).ConfigureAwait(false);
        }

        private async Task<RemoteSubtitleInfo[]> PopulateAsync(string key, Entry entry,
            Func<CancellationToken,Task<IEnumerable<RemoteSubtitleInfo>>> factory)
        {
            await Task.Yield();
            try
            {
                var results = await factory(CancellationToken.None).ConfigureAwait(false);
                var array = (results ?? Array.Empty<RemoteSubtitleInfo>()).Where(x => x != null).ToArray();
                lock (_gate)
                {
                    if (_entries.TryGetValue(key, out var current) && ReferenceEquals(current, entry)) entry.Expires = _clock() + _ttl;
                }
                return array;
            }
            catch
            {
                lock (_gate) { if (_entries.TryGetValue(key, out var current) && ReferenceEquals(current, entry)) _entries.Remove(key); }
                throw;
            }
        }

        private static async Task<T> ObserveAsync<T>(Task<T> task, CancellationToken cancellationToken)
        {
            if (!cancellationToken.CanBeCanceled) return await task.ConfigureAwait(false);
            if (task.IsCompleted) return await task.ConfigureAwait(false);
            var cancelled = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            using (cancellationToken.Register(state => ((TaskCompletionSource<bool>)state).TrySetResult(true), cancelled))
            {
                var first = await Task.WhenAny(task, cancelled.Task).ConfigureAwait(false);
                if (first != task) throw new OperationCanceledException(cancellationToken);
            }
            return await task.ConfigureAwait(false);
        }

        private void RemoveExpired()
        {
            var now = _clock();
            foreach (var pair in _entries.Where(x => x.Value.Expires <= now).ToArray()) _entries.Remove(pair.Key);
        }

        private void EnsureCapacity()
        {
            if (_entries.Count < _capacity) return;
            var remove = _entries.Where(x => x.Value.Task != null && x.Value.Task.IsCompleted)
                .OrderBy(x => x.Value.Accessed).Select(x => x.Key).Take(Math.Max(1, _entries.Count - _capacity + 1)).ToArray();
            foreach (var key in remove) _entries.Remove(key);
        }

        private sealed class Entry
        {
            public Task<RemoteSubtitleInfo[]> Task;
            public DateTimeOffset Expires = DateTimeOffset.MaxValue;
            public long Accessed;
        }
    }
}
