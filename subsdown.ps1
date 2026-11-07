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
    [string]$Python = 'python',
    [string]$YtDlp = 'yt-dlp',
    [string]$FFmpeg = 'ffmpeg',
    [Parameter(Position=1, ValueFromRemainingArguments=$true)][string[]]$YtDlpSubtitleArgs
)
$ErrorActionPreference = 'Stop'
try {
    $pythonCommand = Get-Command $Python -CommandType Application -ErrorAction Stop
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
    $argumentList += @('--yt-dlp', $YtDlp, '--ffmpeg', $FFmpeg)
    if ($YtDlpSubtitleArgs) { $argumentList += @('--subtitle-args') + $YtDlpSubtitleArgs }
    & $pythonCommand.Source @argumentList
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('ERROR: ' + $_.Exception.Message)
    exit 1
}
