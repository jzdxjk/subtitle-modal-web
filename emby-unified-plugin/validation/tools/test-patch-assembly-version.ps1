param(
    [Parameter(Mandatory)][string]$InputPath,
    [Parameter(Mandatory)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$tool = Join-Path $PSScriptRoot 'patch-assembly-version.ps1'
if (-not (Test-Path -LiteralPath $tool)) { throw 'PE version patch tool is missing.' }
$sourcePath = (Resolve-Path -LiteralPath $InputPath).Path
$before = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
$outputPath = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) 'Emby.SubtitleAssistant.dll'
$result = & $tool -InputPath $sourcePath -OutputPath $outputPath | ConvertFrom-Json
if ($result.output_version -ne '1.0.0.1') { throw 'Unexpected output assembly version.' }
if ([Reflection.AssemblyName]::GetAssemblyName($outputPath).Version.ToString() -ne '1.0.0.1') { throw 'Output metadata inspection failed.' }
if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne $before) { throw 'Original DLL changed.' }
[byte[]]$original = [IO.File]::ReadAllBytes($sourcePath)
[byte[]]$patched = [IO.File]::ReadAllBytes($outputPath)
if ($original.Length -ne $patched.Length) { throw 'File length changed.' }
$offset = [int]$result.metadata_version_offset
$changed = 0
for ($i = 0; $i -lt $original.Length; $i++) {
    if ($original[$i] -ne $patched[$i]) {
        if ($i -lt $offset -or $i -ge $offset + 8) { throw 'Byte outside the Assembly version changed.' }
        $changed++
    }
}
if ($changed -eq 0) { throw 'No version byte changed.' }
$rejected = $false
try { & $tool -InputPath $sourcePath -OutputPath $sourcePath | Out-Null } catch { $rejected = $true }
if (-not $rejected) { throw 'In-place patch was not rejected.' }
$rejected = $false
try { & $tool -InputPath $sourcePath -OutputPath $outputPath | Out-Null } catch { $rejected = $true }
if (-not $rejected) { throw 'Existing output was not protected.' }
$result | Add-Member -NotePropertyName verified_changed_byte_count -NotePropertyValue $changed
$result | ConvertTo-Json -Depth 3
