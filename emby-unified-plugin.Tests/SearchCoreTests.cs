using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class SearchCoreTests
{
    [Theory]
    [InlineData("SSIS-157-LTX【2021-08-19】（小宵虎南）出差和一直蔑视的中年性骚扰上司共处一室…直到早晨的绝伦性交HCUP新入社员.mp4", "SSIS-157")]
    [InlineData("SSIS-157-c-无码破解.mp4", "SSIS-157")]
    [InlineData("/media/ABP-999/www.hhd800.com@SSIS-157-CD2.strm", "SSIS-157")]
    [InlineData("C:\\media\\SAVR-00143.mp4", "SAVR-00143")]
    public void ReadsOnlyFilenameAndPreservesNumberSpelling(string path, string expected)
    {
        var identifier = MediaIdentifier.TryParse(path);
        Assert.Equal(expected, identifier?.CanonicalCode);
        Assert.Equal(expected, Assert.Single(identifier.QueryVariants));
    }

    [Theory]
    [InlineData("ssis157.mp4", "SSIS-157")]
    [InlineData("SSIS_157.mp4", "SSIS-157")]
    [InlineData("SAVR00143.mp4", "SAVR-00143")]
    public void OrdinaryCodesUseOneNormalizedQueryWithoutChangingNumericSpelling(string path, string expected)
        => Assert.Equal(expected, Assert.Single(MediaIdentifier.TryParse(path).QueryVariants));

    [Fact]
    public void PreservesTheEntireVideoStem()
    {
        const string stem = "SSIS-157-c-无码破解";
        Assert.Equal(stem, MediaIdentifier.TryParse("/media/" + stem + ".mp4").OriginalStem);
    }

    [Theory]
    [InlineData("FC2-PPV-0123456.mp4")]
    [InlineData("FC2PPV-0123456.strm")]
    [InlineData("FC2-0123456.mkv")]
    public void EveryFc2InputQueriesAllThreeNames(string filename)
        => Assert.Equal(new[] { "FC2-PPV-0123456", "FC2PPV-0123456", "FC2-0123456" }, MediaIdentifier.TryParse(filename).QueryVariants);

    [Theory]
    [InlineData("MIUM-00123.mp4", "300MIUM-00123", "MIUM-00123")]
    [InlineData("200GANA-123.mp4", "200GANA-123", "GANA-123")]
    [InlineData("JNT-123.mp4", "390JNT-123", "JNT-123")]
    [InlineData("IDOL-123.mp4", "250IDOL-123", "IDOL-123")]
    public void ConfirmedAmateurMappingsExpandBothPrefixes(string path, string canonical, string shortName)
    {
        var id = MediaIdentifier.TryParse(path);
        Assert.Equal(canonical, id.CanonicalCode);
        Assert.Equal(new[] { canonical, shortName }, id.QueryVariants);
        Assert.True(id.Matches(shortName + "-CD2.srt"));
    }

    [Fact]
    public void UnknownAmateurNumericPrefixCanExpandOnlyWhatTheFilenameProves()
    {
        var full = MediaIdentifier.TryParse("259LUXU-00123.mp4");
        Assert.Equal(new[] { "259LUXU-00123", "LUXU-00123" }, full.QueryVariants);
        Assert.True(full.Matches("LUXU-123.srt"));
        Assert.False(full.Matches("258LUXU-00123.srt"));
        Assert.Equal("LUXU-00123", Assert.Single(MediaIdentifier.TryParse("LUXU-00123.mp4").QueryVariants));
        Assert.NotNull(MediaIdentifier.TryParse("LUXU-00123 259LUXU-00123.mp4"));
        Assert.Null(MediaIdentifier.TryParse("259LUXU-00123 258LUXU-00123.mp4"));
    }

    [Theory]
    [InlineData("1pondo_010203_004.mp4", "010203-004", "010203_004")]
    [InlineData("caribbeancom-010203-004.mp4", "010203-004", "010203_004")]
    [InlineData("heyzo0123.mp4", "HEYZO-0123", "HEYZO_0123")]
    [InlineData("Tokyo-Hot-n0123-CD1.mp4", "N0123", "N_0123")]
    public void UncensoredAliasesKeepLeadingZeros(string path, string canonical, string alias)
    {
        var id = MediaIdentifier.TryParse(path);
        Assert.Equal(canonical, id.CanonicalCode);
        Assert.Contains(alias, id.QueryVariants);
        Assert.True(id.Matches(alias + ".ass"));
    }

    [Theory]
    [InlineData("movie with no number.mp4")]
    [InlineData("SSIS-157 and SSIS-158.mp4")]
    [InlineData("/media/SSIS-157/actor title.mp4")]
    public void MissingOrConflictingCodesHaveNoFallback(string path)
        => Assert.Null(MediaIdentifier.TryParse(path));

    [Fact]
    public void ExactIdentityRejectsOtherNumbersAndConflictingCandidate()
    {
        var id = MediaIdentifier.TryParse("SSIS-00157-CD1.mp4");
        Assert.True(id.Matches("ssis157-CD2.srt"));
        Assert.False(id.Matches("SSIS-158.srt"));
        Assert.False(id.Matches("SSIS-157 SSIS-158.srt"));
        Assert.False(id.Matches("anonymous subtitle.srt"));
    }

    [Fact]
    public void LegacyEightDigitPaddingIsAcceptedOnlyForCandidateIdentity()
    {
        Assert.True(MediaIdentifier.TryParse("SAVR-00143.mp4").Matches("SAVR-00000143-CD2"));
        Assert.True(MediaIdentifier.TryParse("N0123.mp4").Matches("N-00000123"));
        Assert.Null(MediaIdentifier.TryParse("SAVR-00000143.mp4"));
    }

    [Fact]
    public void RanksAbsoluteDurationDifferenceBeforeFileSize()
    {
        var a = new SubtitleCandidate { Name = "near", DurationSeconds = 99, SizeBytes = 10, StableOrder = 0 };
        var b = new SubtitleCandidate { Name = "large", DurationSeconds = 90, SizeBytes = 10000, StableOrder = 1 };
        var c = new SubtitleCandidate { Name = "same-larger", DurationSeconds = 101, SizeBytes = 20, StableOrder = 2 };
        var d = new SubtitleCandidate { Name = "unknown", SizeBytes = 100000, StableOrder = 3 };
        Assert.Equal(new[] { "same-larger", "near", "large", "unknown" }, SubtitleRanking.Order(new[] { d, b, a, c }, 100).Select(x => x.Name));
        Assert.Equal("unknown", SubtitleRanking.Order(new[] { a, d }, null).First().Name);
    }

    [Fact]
    public void ParsesMaximumAssEndTimeInsteadOfStartTime()
    {
        var data = Encoding.UTF8.GetBytes("[Script Info]\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:49.25,Default,,0,0,0,,字幕,有逗号\nDialogue: 0,0:00:30.00,0:01:10.50,Default,,0,0,0,,字幕");
        var document = Assert.Single(SubtitleContent.ReadAll(data, "ass", "test.ass"));
        Assert.Equal(70.5, document.DurationSeconds);
        Assert.Equal("chi", document.Language);
    }

    [Fact]
    public void ReadsEveryValidSubtitleInZipAndRejectsHtml()
    {
        using var stream = new MemoryStream();
        using (var zip = new ZipArchive(stream, ZipArchiveMode.Create, true))
        {
            foreach (var name in new[] { "a.srt", "b.ssa" })
            {
                using var output = zip.CreateEntry(name).Open();
                var text = name.EndsWith("srt") ? "1\n00:00:01,000 --> 00:00:09,500\n字幕" : "[Events]\nDialogue: Marked=0,0:00:01.00,0:00:12.00,Default,,0,0,0,,字幕";
                var bytes = Encoding.UTF8.GetBytes(text);
                output.Write(bytes);
            }
        }
        var docs = SubtitleContent.ReadAll(stream.ToArray(), "zip", "archive.zip");
        Assert.Equal(2, docs.Count);
        Assert.Equal(new double?[] { 9.5, 12 }, docs.Select(x => x.DurationSeconds));
        Assert.Empty(SubtitleContent.ReadAll(Encoding.UTF8.GetBytes("<html>error</html>"), "srt", "bad.srt"));
    }

    [Fact]
    public async Task AutomationScopeIsIsolatedAndRestoredAfterAwait()
    {
        Assert.False(SearchExecutionContext.IsAutomation);
        var automated = Task.Run(async () =>
        {
            using (SearchExecutionContext.BeginAutomation())
            {
                await Task.Yield();
                Assert.True(SearchExecutionContext.IsAutomation);
                return true;
            }
        });
        await Task.Yield();
        Assert.False(SearchExecutionContext.IsAutomation);
        Assert.True(await automated);
        Assert.False(SearchExecutionContext.IsAutomation);
    }

    [Fact]
    public void BodyCacheExpiresAndEvictsByTotalBytes()
    {
        var now = DateTimeOffset.UtcNow;
        var cache = new SubtitleBodyCache(5, TimeSpan.FromHours(24), () => now);
        cache.Put("a", new byte[] { 1, 2, 3 });
        cache.Put("b", new byte[] { 4, 5, 6 });
        Assert.False(cache.TryGet("a", out _));
        Assert.True(cache.TryGet("b", out _));
        Assert.Equal(3, cache.TotalBytes);
        now += TimeSpan.FromHours(25);
        Assert.False(cache.TryGet("b", out _));
        Assert.Equal(0, cache.TotalBytes);
    }

    [Fact]
    public void CacheEvictsLeastRecentlyUsedEvenWhenClockHasNotTicked()
    {
        var now = DateTimeOffset.UtcNow;
        var cache = new SubtitleBodyCache(6, clock: () => now);
        cache.Put("a", new byte[3]);
        cache.Put("b", new byte[3]);
        Assert.True(cache.TryGet("a", out _));
        cache.Put("c", new byte[3]);
        Assert.True(cache.TryGet("a", out _));
        Assert.False(cache.TryGet("b", out _));
    }

    [Fact]
    public void ExplicitLanguageSuffixIsUsedWhenTextLanguageIsUnknown()
    {
        var bytes = Encoding.UTF8.GetBytes("1\n00:00:01,000 --> 00:00:05,000\nHello there");
        var document = Assert.Single(SubtitleContent.ReadAll(bytes, "srt", "SSIS-157.eng.srt"));
        Assert.Equal("eng", document.Language);
        Assert.False(SubtitleContent.AcceptLanguage("chi", document.Language));
        Assert.Equal("unknown", Assert.Single(SubtitleContent.ReadAll(bytes, "srt", "SSIS-157.srt")).Language);
    }

    [Theory]
    [InlineData("这是中文字幕。人物昵称：あい。", "chi")]
    [InlineData("这是中文字幕，人物昵称是ก。", "chi")]
    [InlineData("这是完整的中文字幕翻译。\nこれは日本語の字幕です。", "chi")]
    [InlineData("これは日本語の字幕です。今日は良い天気ですね。", "jpn")]
    [InlineData("นี่คือคำบรรยายภาษาไทย", "tha")]
    public void LanguageUsesDialogueRatiosInsteadOfOneForeignCharacter(string dialogue, string expected)
    {
        var bytes = Encoding.UTF8.GetBytes("1\n00:00:01,000 --> 00:00:05,000\n" + dialogue);
        Assert.Equal(expected, Assert.Single(SubtitleContent.ReadAll(bytes, "srt", "SSIS-157.srt")).Language);
    }

    [Fact]
    public void ExplicitChineseFilenameHintKeepsChineseBilingualSubtitles()
    {
        var bytes = Encoding.UTF8.GetBytes("1\n00:00:01,000 --> 00:00:05,000\nこれは日本語の字幕です。");
        foreach (var name in new[] { "SSIS-157.chi.srt", "SSIS-157.zh-CN.srt" })
            Assert.Equal("chi", Assert.Single(SubtitleContent.ReadAll(bytes, "srt", name)).Language);
    }

    [Fact]
    public void AssLanguageIgnoresMetadataStyleNamesAndFormattingCommands()
    {
        var bytes = Encoding.UTF8.GetBytes("[Script Info]\nTitle: นี่คือคำบรรยายภาษาไทย\n[Events]\nDialogue: 0,0:00:01.00,0:00:05.00,ภาษาไทย,,0,0,0,,{\\fnภาษาไทย}这是中文字幕。人物昵称：あい。");
        Assert.Equal("chi", Assert.Single(SubtitleContent.ReadAll(bytes, "ass", "SSIS-157.ass")).Language);
        bytes = Encoding.UTF8.GetBytes("[Script Info]\nTitle: 这是中文字幕标题和样式的元数据与正文无关\n[Events]\nDialogue: 0,0:00:01.00,0:00:05.00,Default,,0,0,0,,これは日本語の字幕です。");
        Assert.Equal("jpn", Assert.Single(SubtitleContent.ReadAll(bytes, "ass", "SSIS-157.ass")).Language);
    }

    [Fact]
    public void ArchivesDoNotRecursivelyExpandDisguisedNestedArchives()
    {
        byte[] Archive(string name, byte[] bytes)
        {
            using var output = new MemoryStream();
            using (var zip = new ZipArchive(output, ZipArchiveMode.Create, true))
            using (var entry = zip.CreateEntry(name).Open()) entry.Write(bytes);
            return output.ToArray();
        }
        var nested = Archive("SSIS-157.srt", Encoding.UTF8.GetBytes("1\n00:00:01,000 --> 00:00:05,000\n字幕"));
        var outer = Archive("disguised.srt", nested);
        Assert.Empty(SubtitleContent.ReadAll(outer, "zip", "SSIS-157.zip"));
    }

    [Fact]
    public void NestedAutomationScopesRestoreAfterException()
    {
        using (SearchExecutionContext.BeginAutomation())
        {
            Assert.Throws<InvalidOperationException>((Action)(() =>
            {
                using (SearchExecutionContext.BeginAutomation()) throw new InvalidOperationException();
            }));
            Assert.True(SearchExecutionContext.IsAutomation);
        }
        Assert.False(SearchExecutionContext.IsAutomation);
    }
}
