using System;

namespace Emby.SubtitleAssistant.Automation;

/// <summary>
/// Wraps a failure inside <see cref="SubtitleCompletionService.ProcessAsync"/> together with the
/// stage that was running, so entry points can log the stack trace, item identity and failure
/// stage instead of only the exception type.
/// </summary>
internal sealed class SubtitleCompletionException : Exception
{
    internal string Stage { get; }

    internal SubtitleCompletionException(string stage, string message, Exception innerException)
        : base(message, innerException)
    {
        Stage = string.IsNullOrWhiteSpace(stage) ? "unknown" : stage;
    }
}
