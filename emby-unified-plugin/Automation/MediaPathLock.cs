using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace Emby.SubtitleAssistant.Automation;

internal static class MediaPathLock
{
    private static readonly object Gate = new object();
    private static readonly Dictionary<string, Entry> Entries = new Dictionary<string, Entry>(PathComparer);

    internal static async Task<IDisposable> AcquireAsync(string mediaPath, CancellationToken cancellationToken = default)
    {
        var key = Path.GetFullPath(mediaPath);
        Entry entry;
        lock (Gate)
        {
            if (!Entries.TryGetValue(key,out entry)) Entries[key] = entry = new Entry();
            entry.Users++;
        }

        try
        {
            await entry.Semaphore.WaitAsync(cancellationToken).ConfigureAwait(false);
            return new Lease(key,entry);
        }
        catch
        {
            ReleaseReference(key,entry);
            throw;
        }
    }

    private static void Release(string key, Entry entry)
    {
        entry.Semaphore.Release();
        ReleaseReference(key,entry);
    }

    private static void ReleaseReference(string key, Entry entry)
    {
        lock (Gate)
        {
            entry.Users--;
            if (entry.Users == 0 && Entries.TryGetValue(key,out var current) && ReferenceEquals(current,entry))
                Entries.Remove(key);
        }
    }

    private static StringComparer PathComparer => Path.DirectorySeparatorChar == '\\'
        ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;

    private sealed class Entry
    {
        internal readonly SemaphoreSlim Semaphore = new SemaphoreSlim(1,1);
        internal int Users;
    }

    private sealed class Lease : IDisposable
    {
        private readonly string _key;
        private readonly Entry _entry;
        private int _disposed;

        internal Lease(string key, Entry entry) { _key = key; _entry = entry; }
        public void Dispose()
        {
            if (Interlocked.Exchange(ref _disposed,1) == 0) Release(_key,_entry);
        }
    }
}
