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

$PyScript = Join-Path $ScriptDir "subsmerge.py"
if (-not (Test-Path $PyScript)) {
    Write-Error "Python helper not found: $PyScript"
    exit 2
}

$PythonCommand = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $PythonCommand) {
    [Console]::Error.WriteLine("Python executable not found: $Python")
    exit 2
}
$argsList = @("-X", "utf8", $PyScript, $Folder)

if (-not [string]::IsNullOrWhiteSpace($Output)) {
    $argsList += @("--output", $Output)
}
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
    [Console]::Error.WriteLine($_.Exception.Message)
    $code = 2
}
exit $code
