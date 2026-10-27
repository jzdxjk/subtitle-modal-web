using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
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
    }
    public static class SubtitleRanking
    {
        public static IReadOnlyList<SubtitleCandidate> Order(IEnumerable<SubtitleCandidate> candidates, double? runtime)
            => candidates.OrderBy(x => runtime > 0 ? x.DurationSeconds > 0 ? Math.Abs(x.DurationSeconds.Value - runtime.Value) : double.MaxValue : 0)
                .ThenByDescending(x => x.SizeBytes.HasValue).ThenByDescending(x => x.SizeBytes ?? 0).ThenBy(x => x.StableOrder).ToArray();
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
}
