# Offline index/batch/report wrapper. No dependencies are installed implicitly.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("index", "prepare", "status", "accept-report")][string]$Command,
    [Parameter(Mandatory = $true, Position = 1)][string]$Folder,
    [Parameter(Position = 2)][string]$Report = "",
    [string]$Manifest = "",
    [string]$Output = "",
    [int]$MaxChars = 30000,
    [switch]$Overwrite,
    [switch]$Json,
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch {}
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
function Write-LaunchFailure([string]$Message) {
    [Console]::Error.WriteLine($Message)
    if ($Json) {
        $ProductVersion = (Get-Content -LiteralPath (Join-Path $ScriptDir "VERSION") -Raw).Trim()
        [ordered]@{ schema = "subsbatch.result.v1"; version = $ProductVersion;
            command = $Command; exit_code = 2; error = $Message } | ConvertTo-Json -Compress
    }
}
$PyScript = Join-Path $ScriptDir "subsbatch.py"
$PythonCommand = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $PythonCommand) { Write-LaunchFailure "Python executable not found: $Python"; exit 2 }
if (-not (Test-Path -LiteralPath $PyScript)) { Write-LaunchFailure "Python helper not found: $PyScript"; exit 2 }
$argsList = @("-X", "utf8", $PyScript, $Command, $Folder)
if ($Report) { $argsList += $Report }
if ($Manifest) { $argsList += @("--manifest", $Manifest) }
if ($Output) { $argsList += @("--output", $Output) }
if ($Command -eq "prepare") { $argsList += @("--max-chars", [string]$MaxChars) }
if ($Overwrite) { $argsList += "--overwrite" }
if ($Json) { $argsList += "--json" }
try {
    & $PythonCommand.Source @argsList
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 2 }
} catch { Write-LaunchFailure $_.Exception.Message; $code = 2 }
exit $code
