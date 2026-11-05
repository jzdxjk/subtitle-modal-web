using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;

namespace Emby.SubtitleAssistant.Automation;

public static class DownloadWriteObserver
{
    internal static Func<Stream,string,Stream> Factory { get; set; }
    public static Stream Wrap(Stream stream, string mediaPath)
    {
        if (SearchExecutionContext.IsAutomation || string.IsNullOrEmpty(mediaPath)) return stream;
        return Factory?.Invoke(stream,mediaPath) ?? stream;
    }

    internal static Stream Track(Stream stream, IEnumerable<string> directories, string originalStem, Action onWritten)
    {
        var roots = directories.Where(path => !string.IsNullOrWhiteSpace(path)).Distinct(StringComparer.Ordinal).ToArray();
        var before = Snapshot(roots,originalStem);
        return new TrackedStream(stream,() =>
        {
            var after = Snapshot(roots,originalStem);
            if (after.Any(pair => !before.TryGetValue(pair.Key,out var stamp) || !stamp.Equals(pair.Value))) onWritten();
        });
    }

    private static Dictionary<string,Tuple<long,long>> Snapshot(string[] directories, string stem)
    {
        var result = new Dictionary<string,Tuple<long,long>>(StringComparer.Ordinal);
        foreach (var root in directories)
        {
            try
            {
                if (!Directory.Exists(root)) continue;
                foreach (var path in Directory.EnumerateFiles(root,"*",SearchOption.TopDirectoryOnly))
                {
                    var name = Path.GetFileName(path);
                    var extension = Path.GetExtension(path).TrimStart('.').ToLowerInvariant();
                    if (!name.StartsWith(stem + ".",StringComparison.Ordinal) || !SubtitleContent.IsSupported(extension)) continue;
                    var info = new FileInfo(path);
                    if (info.Length > 0) result[path] = Tuple.Create(info.Length,info.LastWriteTimeUtc.Ticks);
                }
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
        return result;
    }

    private sealed class TrackedStream : Stream
    {
        private readonly Stream _inner;
        private Action _completed;
        public TrackedStream(Stream inner, Action completed) { _inner = inner; _completed = completed; }
        public override bool CanRead => _inner.CanRead;
        public override bool CanSeek => _inner.CanSeek;
        public override bool CanWrite => _inner.CanWrite;
        public override long Length => _inner.Length;
        public override long Position { get => _inner.Position; set => _inner.Position = value; }
        public override void Flush() => _inner.Flush();
        public override int Read(byte[] buffer,int offset,int count) => _inner.Read(buffer,offset,count);
        public override Task<int> ReadAsync(byte[] buffer,int offset,int count,CancellationToken ct) => _inner.ReadAsync(buffer,offset,count,ct);
        public override ValueTask<int> ReadAsync(Memory<byte> buffer,CancellationToken ct = default) => _inner.ReadAsync(buffer,ct);
        public override long Seek(long offset,SeekOrigin origin) => _inner.Seek(offset,origin);
        public override void SetLength(long value) => _inner.SetLength(value);
        public override void Write(byte[] buffer,int offset,int count) => _inner.Write(buffer,offset,count);
        public override Task CopyToAsync(Stream destination,int bufferSize,CancellationToken ct) => _inner.CopyToAsync(destination,bufferSize,ct);
        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                var callback = Interlocked.Exchange(ref _completed,null);
                try { _inner.Dispose(); }
                finally { callback?.Invoke(); }
            }
            base.Dispose(disposing);
        }
    }
}
