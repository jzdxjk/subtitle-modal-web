using System;
using System.Buffers.Binary;
using System.IO;
using System.Linq;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Threading;
using Emby.SubtitleAssistant.Updates;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class UpdateInstallerTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "subtitle-assistant-update-" + Guid.NewGuid().ToString("N"));
    private readonly byte[] _original = File.ReadAllBytes(typeof(Plugin).Assembly.Location);
    private readonly string _path;
    public UpdateInstallerTests()
    {
        Directory.CreateDirectory(_root); _path = Path.Combine(_root, "Emby.SubtitleAssistant.dll");
        File.WriteAllBytes(_path, _original);
    }
    public void Dispose() => Directory.Delete(_root, true);

    internal static byte[] WithVersion(byte[] source, Version version)
    {
        var bytes = source.ToArray();
        using var pe = new PEReader(new MemoryStream(bytes));
        var reader = pe.GetMetadataReader();
        var offset = pe.PEHeaders.MetadataStartOffset + reader.GetTableMetadataOffset(TableIndex.Assembly) + 4;
        var values = new[] { version.Major, version.Minor, version.Build, version.Revision };
        for (var i = 0; i < 4; i++) BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(offset + i * 2, 2), (ushort)values[i]);
        return bytes;
    }

    internal static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private UpdateManifest For(byte[] candidate, string version = "1.0.0.1")
    {
        var manifest = UpdateManifestTests.Manifest(version); manifest.sha256 = Hash(candidate); return manifest;
    }

    [Fact]
    public void ValidPackageAtomicallyReplacesFileAndKeepsOriginalBackup()
    {
        var candidate = WithVersion(_original, new Version(1, 0, 0, 1));
        var result = PackageInstaller.Install(candidate, For(candidate), _path, new Version(1, 0, 0, 0), CancellationToken.None);
        Assert.True(result.Installed);
        Assert.Equal(candidate, File.ReadAllBytes(_path));
        Assert.EndsWith(".bak", result.BackupPath);
        Assert.Equal(_original, File.ReadAllBytes(result.BackupPath));
        Assert.Empty(Directory.GetFiles(Path.Combine(_root, ".subtitle-assistant-update"), "*.bin"));
    }

    [Fact]
    public void PendingDiskVersionPreventsRepeatedReplacementBeforeRestart()
    {
        var candidate = WithVersion(_original, new Version(1, 0, 0, 1)); File.WriteAllBytes(_path, candidate);
        var result = PackageInstaller.Install(candidate, For(candidate), _path, new Version(1, 0, 0, 0), CancellationToken.None);
        Assert.False(result.Installed);
        Assert.Equal(candidate, File.ReadAllBytes(_path));
    }

    [Fact]
    public void BadHashCannotChangeOriginal()
    {
        var candidate = WithVersion(_original, new Version(1, 0, 0, 1)); var manifest = For(candidate); manifest.sha256 = new string('0', 64);
        Assert.Throws<InvalidDataException>(() => PackageInstaller.Install(candidate, manifest, _path, new Version(1, 0, 0, 0), CancellationToken.None));
        Assert.Equal(_original, File.ReadAllBytes(_path));
    }

    [Fact]
    public void WrongAssemblyNameOrVersionCannotChangeOriginal()
    {
        var wrongName = WithVersion(File.ReadAllBytes(typeof(UpdateInstallerTests).Assembly.Location), new Version(1, 0, 0, 1));
        Assert.Throws<InvalidDataException>(() => PackageInstaller.Install(wrongName, For(wrongName), _path, new Version(1, 0, 0, 0), CancellationToken.None));
        var wrongVersion = WithVersion(_original, new Version(1, 0, 0, 1));
        Assert.Throws<InvalidDataException>(() => PackageInstaller.Install(wrongVersion, For(wrongVersion, "1.0.0.2"), _path, new Version(1, 0, 0, 0), CancellationToken.None));
        Assert.Equal(_original, File.ReadAllBytes(_path));
    }

    [Fact]
    public void CancellationAndReplacementFailureKeepOriginalAndCleanStaging()
    {
        var candidate = WithVersion(_original, new Version(1, 0, 0, 1));
        Assert.Throws<OperationCanceledException>(() => PackageInstaller.Install(candidate, For(candidate), _path, new Version(1, 0, 0, 0), new CancellationToken(true)));
        Assert.Throws<IOException>(() => PackageInstaller.Install(candidate, For(candidate), _path, new Version(1, 0, 0, 0), CancellationToken.None,
            (_, _, _) => throw new IOException("simulated replace failure")));
        Assert.Equal(_original, File.ReadAllBytes(_path));
        Assert.Empty(Directory.GetFiles(Path.Combine(_root, ".subtitle-assistant-update"), "*.bin"));
    }

    [Fact]
    public void InstallerCannotOverwriteAnotherPlugin()
    {
        var candidate = WithVersion(_original, new Version(1, 0, 0, 1)); var other = Path.Combine(_root, "other.dll"); File.WriteAllBytes(other, _original);
        Assert.Throws<InvalidDataException>(() => PackageInstaller.Install(candidate, For(candidate), other, new Version(1, 0, 0, 0), CancellationToken.None));
        Assert.Equal(_original, File.ReadAllBytes(other));
    }
}
