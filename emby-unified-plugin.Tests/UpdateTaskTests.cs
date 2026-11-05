using System;
using System.Linq;
using Emby.SubtitleAssistant.Updates;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class UpdateTaskTests
{
    [Fact]
    public void NativeUpdateTaskHasStableKeyAndTwentyFourHourDefault()
    {
        var task = new UpdateTask(null, null, null, null);
        Assert.Equal("SubtitleAssistantUpdate", task.Key);
        Assert.Equal("字幕助手", task.Category);
        var trigger = Assert.Single(task.GetDefaultTriggers());
        Assert.Equal("IntervalTrigger", trigger.Type);
        Assert.Equal(TimeSpan.FromHours(24).Ticks, trigger.IntervalTicks);
    }
}
