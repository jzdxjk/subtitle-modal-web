using System;
using System.IO;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Automation;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public sealed class MediaPathLockTests
{
    [Fact]
    public async Task SameMediaPathSerializesButDifferentVersionsCanProceed()
    {
        var directory = Path.Combine(Path.GetTempPath(),"subtitle-assistant-lock-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var mediaPath = Path.Combine(directory,"ABC-123.mp4");
        var first = await MediaPathLock.AcquireAsync(mediaPath);
        try
        {
            using (await MediaPathLock.AcquireAsync(Path.Combine(directory,"ABC-123-4k.mp4"))) { }
            var waiting = MediaPathLock.AcquireAsync(mediaPath);
            Assert.False(waiting.IsCompleted);
            var decisionAfterLock = SubtitleFileDecision.None;
            var recheck = waiting.ContinueWith(async acquired =>
            {
                using (await acquired) decisionAfterLock = SubtitleFilePolicy.Check(mediaPath);
            },TaskScheduler.Default).Unwrap();
            File.WriteAllText(Path.Combine(directory,"ABC-123.zh-CN.srt"),"new subtitle");
            first.Dispose();
            await recheck.WaitAsync(TimeSpan.FromSeconds(2));
            Assert.Equal(SubtitleFileDecision.MatchingSubtitle,decisionAfterLock);
        }
        finally
        {
            first.Dispose();
            Directory.Delete(directory,true);
        }
    }
}
