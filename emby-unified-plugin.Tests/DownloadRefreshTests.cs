using System;
using System.IO;
using Emby.SubtitleAssistant.Automation;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class DownloadRefreshTests
{
    [Theory]
    [InlineData("abc-123-4k")]
    [InlineData("abc-123-无码破解")]
    [InlineData("abc-123-4k-无码破解")]
    public void NativeFilenameWithLanguageTagRefreshesAfterSubtitleWrite(string originalStem)
    {
        using var fixture = new DirectoryFixture();
        var refreshed = 0;
        var filename = originalStem + ".zh-CN.srt";
        using (var stream = DownloadWriteObserver.Track(new MemoryStream(new byte[3]), new[] { fixture.Path }, originalStem, () => refreshed++))
        {
            File.WriteAllText(System.IO.Path.Combine(fixture.Path, filename), "new subtitle");
            Assert.Equal(0, refreshed);
        }
        Assert.Equal(1, refreshed);
    }

    [Fact] public void OnlyRefreshesAfterNativeStreamClosesAndMatchingFileWasWritten()
    {
        using var fixture = new DirectoryFixture();
        var refreshed = 0;
        var stream = DownloadWriteObserver.Track(new MemoryStream(new byte[3]),new[] { fixture.Path },"SSIS-157-c-无码破解",() => refreshed++);
        File.WriteAllText(System.IO.Path.Combine(fixture.Path,"SSIS-157-c-无码破解.zh-CN.srt"),"new subtitle");
        Assert.Equal(0,refreshed);
        stream.Dispose(); stream.Dispose();
        Assert.Equal(1,refreshed);
    }

    [Fact] public void DoesNotRefreshForRemoteStreamWithoutLocalWriteOrWrongStem()
    {
        using var fixture = new DirectoryFixture(); var refreshed = 0;
        using (DownloadWriteObserver.Track(new MemoryStream(),new[] { fixture.Path },"SSIS-157-c-无码破解",() => refreshed++))
            File.WriteAllText(System.IO.Path.Combine(fixture.Path,"SSIS-157.zh-CN.srt"),"wrong stem");
        Assert.Equal(0,refreshed);
    }

    [Fact] public void PreexistingUnchangedSubtitleDoesNotPretendNewDownloadSucceeded()
    {
        using var fixture = new DirectoryFixture(); var refreshed = 0;
        var filename = System.IO.Path.Combine(fixture.Path,"SSIS-157.zh-CN.srt");
        File.WriteAllText(filename,"old subtitle");
        using (DownloadWriteObserver.Track(new MemoryStream(),new[] { fixture.Path },"SSIS-157",() => refreshed++)) { }
        Assert.Equal(0,refreshed);
        using (DownloadWriteObserver.Track(new MemoryStream(),new[] { fixture.Path },"SSIS-157",() => refreshed++))
            File.WriteAllText(filename,"changed subtitle with a different size");
        Assert.Equal(1,refreshed);
    }

    private sealed class DirectoryFixture : IDisposable
    {
        internal string Path { get; } = System.IO.Path.Combine(System.IO.Path.GetTempPath(),"subtitle-assistant-write-watch-" + Guid.NewGuid().ToString("N"));
        public DirectoryFixture() => Directory.CreateDirectory(Path);
        public void Dispose() { foreach (var file in Directory.GetFiles(Path)) File.Delete(file); Directory.Delete(Path); }
    }
}
