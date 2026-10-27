#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$InputPath,
    [Parameter(Mandatory)][string]$OutputPath,
    [string]$Version = '1.0.0.1'
)
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw 'Version must have four numeric components.' }
$targetVersion = [version]$Version
$parts = @($targetVersion.Major, $targetVersion.Minor, $targetVersion.Build, $targetVersion.Revision)
if (@($parts | Where-Object { $_ -gt 65535 }).Count) { throw 'Assembly version components must fit UInt16.' }
$inputFile = (Resolve-Path -LiteralPath $InputPath).Path
$outputFile = [IO.Path]::GetFullPath($OutputPath)
if ([string]::Equals($inputFile, $outputFile, [StringComparison]::OrdinalIgnoreCase)) { throw 'Input and output must be different files.' }
if (Test-Path -LiteralPath $outputFile) { throw 'Output already exists; choose a new output path.' }
$identity = [Reflection.AssemblyName]::GetAssemblyName($inputFile)
if ($identity.Name -ne 'Emby.SubtitleAssistant') { throw 'Input must be Emby.SubtitleAssistant.dll.' }
if ($identity.GetPublicKey().Length -gt 0) { throw 'This validation tool cannot patch signed assemblies.' }

function Get-BytesSha256([byte[]]$Data) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($Data)).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

[byte[]]$original = [IO.File]::ReadAllBytes($inputFile)
[byte[]]$patched = $original.Clone()
$sourceSha = Get-BytesSha256 $original
$stream = [IO.MemoryStream]::new($original, $false)
$pe = [Reflection.PortableExecutable.PEReader]::new($stream)
try {
    $reader = [Reflection.Metadata.PEReaderExtensions]::GetMetadataReader($pe)
    $offset = $pe.PEHeaders.MetadataStartOffset + [Reflection.Metadata.Ecma335.MetadataReaderExtensions]::GetTableMetadataOffset(
        $reader, [Reflection.Metadata.Ecma335.TableIndex]::Assembly) + 4
    for ($i = 0; $i -lt 4; $i++) {
        $patched[$offset + 2 * $i] = $parts[$i] -band 255
        $patched[$offset + 2 * $i + 1] = $parts[$i] -shr 8
    }
}
finally { $pe.Dispose(); $stream.Dispose() }

[void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($outputFile))
$created = $false
try {
    $output = [IO.FileStream]::new($outputFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $created = $true
    try { $output.Write($patched, 0, $patched.Length); $output.Flush($true) }
    finally { $output.Dispose() }
    $result = [Reflection.AssemblyName]::GetAssemblyName($outputFile)
    if ($result.Name -ne $identity.Name -or $result.Version -ne $targetVersion) { throw 'Patched assembly metadata verification failed.' }
    if ((Get-BytesSha256 ([IO.File]::ReadAllBytes($inputFile))) -ne $sourceSha) { throw 'Source DLL changed during validation.' }
    [pscustomobject]@{
        source_path = $inputFile
        output_path = $outputFile
        source_version = $identity.Version.ToString()
        output_version = $result.Version.ToString()
        source_sha256 = $sourceSha
        output_sha256 = Get-BytesSha256 $patched
        metadata_version_offset = $offset
    } | ConvertTo-Json -Depth 3
}
catch {
    if ($created -and (Test-Path -LiteralPath $outputFile)) { Remove-Item -LiteralPath $outputFile }
    throw
}
