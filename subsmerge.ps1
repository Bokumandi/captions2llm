# subsmerge.ps1
# PowerShell wrapper for subsmerge.py.
#
# Usage:
#   .\subsmerge.ps1 "C:\path\to\subsdown_output\playlist_folder"
#   .\subsmerge.ps1 "folder" -Pretty
#   .\subsmerge.ps1 "folder" -Output ".\my_dataset.json"

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Folder,

    [Parameter(Position = 1)]
    [string]$Output = "",

    [string]$MarkdownOutput = "",
    [switch]$TextOnly,
    [switch]$Json,
    [switch]$Pretty,
    [switch]$IncludeAllJson,
    [switch]$NoOriginal,
    [switch]$FailOnError,
    [switch]$Overwrite,

    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ScriptDir)) {
    $ScriptDir = (Get-Location).Path
}

function Write-LaunchFailure([string]$Message) {
    [Console]::Error.WriteLine($Message)
    if ($Json) {
        $VersionFile = Join-Path $ScriptDir "VERSION"
        $ProductVersion = "unknown"
        if (Test-Path -LiteralPath $VersionFile) {
            $ProductVersion = (Get-Content -LiteralPath $VersionFile -Raw).Trim()
        }
        [ordered]@{ schema = "subsmerge.result.v1"; version = $ProductVersion;
            exit_code = 2; output_json = $null; output_markdown = $null;
            error_log = $null; item_count = 0; ignored_count = 0; error_count = 0;
            error = $Message } | ConvertTo-Json -Compress
    }
}

$PyScript = Join-Path $ScriptDir "subsmerge.py"
if (-not (Test-Path $PyScript)) {
    Write-LaunchFailure "Python helper not found: $PyScript"
    exit 2
}

$PythonCommand = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $PythonCommand) {
    Write-LaunchFailure "Python executable not found: $Python"
    exit 2
}
$argsList = @("-X", "utf8", $PyScript, $Folder)

if (-not [string]::IsNullOrWhiteSpace($Output)) {
    $argsList += @("--output", $Output)
}
if (-not [string]::IsNullOrWhiteSpace($MarkdownOutput)) {
    $argsList += @("--markdown-output", $MarkdownOutput)
}
if ($TextOnly) { $argsList += "--text-only" }
if ($Json) { $argsList += "--json" }
if ($Pretty) {
    $argsList += "--pretty"
}
if ($IncludeAllJson) {
    $argsList += "--include-all-json"
}
if ($NoOriginal) {
    $argsList += "--no-original"
}
if ($FailOnError) {
    $argsList += "--fail-on-error"
}

if ($Overwrite) {
    $argsList += "--overwrite"
}

try {
    & $PythonCommand.Source @argsList
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 2 }
}
catch {
    Write-LaunchFailure $_.Exception.Message
    $code = 2
}
exit $code
