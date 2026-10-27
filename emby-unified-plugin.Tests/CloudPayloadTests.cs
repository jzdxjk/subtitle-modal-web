using System;
using System.Collections.Generic;
using Emby.SubtitleAssistant.Cloud;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class CloudPayloadTests
{
    [Theory]
    [InlineData("/Emby/media/ABP-192.mp4", "/Emby=/root\n/Emby/media=/videos", "/videos/ABP-192.mp4")]
    [InlineData("C:\\MOVIES\\ABP-192.mp4", "c:\\movies=/media", "/media/ABP-192.mp4")]
    [InlineData("/movies-other/a.mp4", "/movies=/media", "/movies-other/a.mp4")]
    public void PathMappingUsesLongestPrefixAndDirectoryBoundaries(string path, string mappings, string expected)
        => Assert.Equal(expected, CloudPayload.MapPath(path, mappings));

    [Theory]
    [InlineData("a.mp4", "https://stream.invalid/a", "native")]
    [InlineData("a.STRM", "#comment\nhttps://stream.invalid/a?secret=hidden", "strm-http")]
    [InlineData("a.strm", " /mnt/videos/a.mp4 ", "strm-local")]
    [InlineData("a.strm", "", "native")]
    public void StrmClassificationKeepsStrmPath(string path, string content, string expected)
        => Assert.Equal(expected, CloudPayload.TaskTypeFor(path, content));

    [Fact]
    public void SubmissionKeepsOriginalIdentityMappedStrmPathAndAudioMetadata()
    {
        var media = new CloudMediaInfo
        {
            ItemId = "42", Path = "/emby/300MIUM-1336.strm", Title = "Original title",
            AvCode = "300MIUM-1336", Type = "Movie", StrmContent = "https://video.invalid/signed?token=hidden",
            Audio = new CloudAudioInfo { Index = 2, Codec = "aac", Channels = 2, BitRate = 160000, SampleRate = 48000 }
        };
        var payload = CloudPayload.Create(media, "/emby=/media");
        Assert.Equal("/media/300MIUM-1336.strm", payload["input_path"]);
        Assert.Equal("300MIUM-1336", payload["av_code"]);
        Assert.Equal("strm-http", payload["task_type"]);
        Assert.Equal(false, payload["overwrite"]);
        Assert.Equal(new[] { "srt" }, Assert.IsType<string[]>(payload["formats"]));
        var audio = Assert.IsType<Dictionary<string, object>>(payload["audio_stream"]);
        Assert.Equal(2, audio["index"]);
        Assert.Equal(160000, audio["bit_rate"]);
        Assert.Equal(48000, audio["sample_rate"]);
        Assert.DoesNotContain("signed", string.Join(" ", payload.Values));
    }

    [Fact]
    public void UnsupportedContainerTypesCannotSubmit()
        => Assert.Throws<ArgumentException>(() => CloudPayload.Create(new CloudMediaInfo { Type = "Series", Path = "/a" }, ""));
}
