# Windows compatibility entry point. Python owns native I/O and UTF-8 handling.
[CmdletBinding()]
param(
    [Parameter(Position=0)][string]$Url,
    [string]$InputFile,
    [string]$OutRoot,
    [string]$Language,
    [switch]$Manual,
    [switch]$CurrentVideoOnly,
    [switch]$KeepWork,
    [switch]$ProcessAllDownloadedSubtitles,
    [string]$Resume,
    [switch]$Merge,
    [switch]$TextOnly,
    [Nullable[int]]$MaxVideos,
    [switch]$Json,
    [string]$Python = 'python',
    [string]$YtDlp = 'yt-dlp',
    [string]$FFmpeg = 'ffmpeg',
    [Parameter(Position=1, ValueFromRemainingArguments=$true)][string[]]$YtDlpSubtitleArgs
)
$ErrorActionPreference = 'Stop'
try {
    $pythonCommand = Get-Command $Python -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $argumentList = @('-X', 'utf8', (Join-Path $PSScriptRoot 'subsdown.py'))
    if ($Url) { $argumentList += $Url }
    foreach ($pair in @(@('--input-file', $InputFile), @('--out-root', $OutRoot), @('--language', $Language), @('--resume', $Resume))) {
        if ($pair[1]) { $argumentList += $pair }
    }
    if ($Manual) { $argumentList += '--manual' }
    if ($CurrentVideoOnly) { $argumentList += '--current-video-only' }
    if ($KeepWork) { $argumentList += '--keep-work' }
    if ($ProcessAllDownloadedSubtitles) { $argumentList += '--process-all' }
    if ($Merge) { $argumentList += '--merge' }
    if ($TextOnly) { $argumentList += '--text-only' }
    if ($null -ne $MaxVideos) { $argumentList += @('--max-videos', [string]$MaxVideos) }
    if ($Json) { $argumentList += '--json' }
    $argumentList += @('--yt-dlp', $YtDlp, '--ffmpeg', $FFmpeg)
    if ($YtDlpSubtitleArgs) { $argumentList += @('--subtitle-args') + $YtDlpSubtitleArgs }
    & $pythonCommand.Source @argumentList
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('ERROR: ' + $_.Exception.Message)
    if ($Json) {
        $result = [ordered]@{
            schema_version = 'subsdown.result.v1'
            product_version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION') -Raw).Trim()
            exit_code = 1; manifest_path = $null; output_root = $null
            summary = @{ success = 0; unavailable = 0; failed = 0 }
            merged_json = $null; merged_markdown = $null; error = $_.Exception.Message
        }
        [Console]::Out.WriteLine(($result | ConvertTo-Json -Compress))
    }
    exit 1
}
