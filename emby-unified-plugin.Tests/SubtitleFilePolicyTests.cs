using System;
using System.IO;
using Emby.SubtitleAssistant.Automation;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class SubtitleFilePolicyTests
{
    [Fact]
    public void DifferentVersionSubtitleDoesNotBlockCurrentMedia()
    {
        WithDirectory(directory =>
        {
            File.WriteAllText(Path.Combine(directory,"ABC-123.srt"),"subtitle");
            Assert.Equal(SubtitleFileDecision.None,SubtitleFilePolicy.Check(Path.Combine(directory,"ABC-123-4k.mp4")));
        });
    }

    [Theory]
    [InlineData("ABC-123-4k.zh-CN.srt")]
    [InlineData("ABC-123-4k.commentary.ass")]
    [InlineData("ABC-123-4k.ssa")]
    [InlineData("ABC-123-4k.vtt")]
    public void MatchingVersionAndSupportedExtensionSkipAutomaticCompletion(string subtitleName)
    {
        WithDirectory(directory =>
        {
            File.WriteAllText(Path.Combine(directory,subtitleName),"subtitle");
            Assert.Equal(SubtitleFileDecision.MatchingSubtitle,SubtitleFilePolicy.Check(Path.Combine(directory,"ABC-123-4k.mp4")));
        });
    }

    [Fact]
    public void VobSubRequiresMatchingSubAndIdxFiles()
    {
        WithDirectory(directory =>
        {
            var media = Path.Combine(directory,"ABC-123-4k.mp4");
            File.WriteAllText(Path.Combine(directory,"ABC-123-4k.zh-CN.idx"),"idx");
            Assert.Equal(SubtitleFileDecision.None,SubtitleFilePolicy.Check(media));
            File.WriteAllText(Path.Combine(directory,"ABC-123-4k.zh-CN.sub"),"sub");
            Assert.Equal(SubtitleFileDecision.MatchingSubtitle,SubtitleFilePolicy.Check(media));
        });
    }

    [Theory]
    [InlineData("ABC-123-中字.mp4", "ChineseFilenameMarker")]
    [InlineData("ABC-123-简中.mp4", "ChineseFilenameMarker")]
    [InlineData("ABC-123-中文字幕.mp4", "ChineseFilenameMarker")]
    [InlineData("ABC-123-C.mp4", "ChineseFilenameMarker")]
    [InlineData("ABC-123-无中字.mp4", "None")]
    [InlineData("ABC-123-无简中.mp4", "None")]
    [InlineData("ABC-123-无中文字幕.mp4", "None")]
    public void ChineseFilenameMarkersAndNegationsAreHandled(string filename, string expected)
    {
        WithDirectory(directory => Assert.Equal(expected,SubtitleFilePolicy.Check(Path.Combine(directory,filename)).ToString()));
    }

    [Fact]
    public void DirectoryReadFailureIsReportedAsSkipDecision()
    {
        var missingDirectory = Path.Combine(Path.GetTempPath(),"subtitle-assistant-missing-" + Guid.NewGuid().ToString("N"));
        Exception failure = null;
        var decision = SubtitleFilePolicy.Check(Path.Combine(missingDirectory,"ABC-123.mp4"),error => failure = error);
        Assert.Equal(SubtitleFileDecision.DirectoryReadFailure,decision);
        Assert.IsType<DirectoryNotFoundException>(failure);
    }

    private static void WithDirectory(Action<string> test)
    {
        var directory = Path.Combine(Path.GetTempPath(),"subtitle-assistant-files-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try { test(directory); }
        finally { Directory.Delete(directory,true); }
    }
}
