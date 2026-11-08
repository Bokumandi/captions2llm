# No parameter binder: PS5.1 must preserve named, native and remaining arguments.
# The operation-specific maps translate the documented PowerShell spellings only.
$ErrorActionPreference = 'Stop'
$tokens = @($args | ForEach-Object {
    # Hashtable splatting supplies '-Name:' and its typed value as two tokens.
    if ($_ -is [string] -and $_.StartsWith('-') -and $_.EndsWith(':')) { $_.Substring(0, $_.Length - 1) } else { $_ }
})
$command = if ($tokens.Count) { [string]$tokens[0] } else { '' }
$machine = $false
for ($j = 0; $j -lt $tokens.Count; $j++) {
    if ($tokens[$j] -ceq '--json' -or ($tokens[$j] -ieq '-Json' -and
        -not ($j + 1 -lt $tokens.Count -and $tokens[$j + 1] -is [bool] -and -not $tokens[$j + 1]))) { $machine = $true }
}
$productVersion = 'unknown'
$versionFile = Join-Path $PSScriptRoot 'VERSION'
if (Test-Path -LiteralPath $versionFile) { $productVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim() }
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch {}

function Write-LaunchFailure([string]$Message) {
    $code = if ($command -eq 'download') { 1 } else { 2 }
    [Console]::Error.WriteLine('ERROR: ' + $Message)
    if ($machine) {
        if ($command -eq 'download') {
            $result = [ordered]@{ schema_version = 'subsdown.result.v1'; product_version = $productVersion
                exit_code = $code; manifest_path = $null; output_root = $null
                summary = @{ success = 0; unavailable = 0; failed = 0 }
                merged_json = $null; merged_markdown = $null; index_json = $null; index_markdown = $null }
        } elseif ($command -eq 'merge') {
            $result = [ordered]@{ schema = 'subsmerge.result.v1'; version = $productVersion
                exit_code = $code; output_json = $null; output_markdown = $null; error_log = $null
                item_count = 0; ignored_count = 0; error_count = 0 }
        } else {
            $schema = if ($command -in @('index', 'prepare', 'status', 'accept-report')) { 'subsbatch.result.v1' } else { 'captions2llm.result.v1' }
            $result = [ordered]@{ schema = $schema; version = $productVersion; command = $command; exit_code = $code }
        }
        $result.error = $Message
        [Console]::Out.WriteLine(($result | ConvertTo-Json -Compress))
    }
    return $code
}

try {
    $valueOptions = @{}
    $switchOptions = @{ '-Json' = '--json' }
    switch ($command) {
        'download' {
            $valueOptions = @{ '-Url' = ''; '-InputFile' = '--input-file'; '-OutRoot' = '--out-root'
                '-Language' = '--language'; '-Resume' = '--resume'; '-MaxVideos' = '--max-videos'
                '-YtDlp' = '--yt-dlp'; '-FFmpeg' = '--ffmpeg' }
            $switchOptions += @{ '-Manual' = '--manual'; '-CurrentVideoOnly' = '--current-video-only'
                '-KeepWork' = '--keep-work'; '-ProcessAllDownloadedSubtitles' = '--process-all'
                '-Merge' = '--merge'; '-TextOnly' = '--text-only' }
        }
        'merge' {
            $valueOptions = @{ '-Folder' = ''; '-Output' = '--output'; '-MarkdownOutput' = '--markdown-output' }
            $switchOptions += @{ '-TextOnly' = '--text-only'; '-Pretty' = '--pretty'; '-IncludeAllJson' = '--include-all-json'
                '-NoOriginal' = '--no-original'; '-FailOnError' = '--fail-on-error'; '-Overwrite' = '--overwrite' }
        }
        { $_ -in @('index', 'prepare') } {
            $valueOptions = @{ '-Folder' = ''; '-Manifest' = '--manifest'; '-Output' = '--output' }
            if ($command -eq 'prepare') { $valueOptions['-MaxChars'] = '--max-chars' }
        }
        'status' { $valueOptions = @{ '-Folder' = '' } }
        'accept-report' { $valueOptions = @{ '-Folder' = ''; '-Report' = '' }; $switchOptions['-Overwrite'] = '--overwrite' }
    }
    $python = 'python'
    $forwarded = @()
    $subtitleArgs = @()
    $positionals = @()
    $namedPositionals = @{}
    for ($i = 1; $i -lt $tokens.Count; $i++) {
        $token = [string]$tokens[$i]
        if ($token -eq '--subtitle-args' -and $command -eq 'download') {
            if ($i + 1 -lt $tokens.Count) { $subtitleArgs += $tokens[($i + 1)..($tokens.Count - 1)] }
            break
        }
        if ($token -ceq '--') {
            $forwarded += $tokens[$i..($tokens.Count - 1)]
            break
        }
        if ($token -ieq '-Python') {
            if (++$i -ge $tokens.Count) { throw 'Missing value for -Python' }
            $python = [string]$tokens[$i]
        } elseif ($valueOptions.ContainsKey($token)) {
            if (++$i -ge $tokens.Count) { throw "Missing value for $token" }
            if ($valueOptions[$token]) { $forwarded += @($valueOptions[$token], [string]$tokens[$i]) }
            else { $namedPositionals[$token] = [string]$tokens[$i] }
        } elseif ($switchOptions.ContainsKey($token)) {
            $enabled = $true
            if ($i + 1 -lt $tokens.Count -and $tokens[$i + 1] -is [bool]) { $enabled = $tokens[++$i] }
            if ($enabled) { $forwarded += $switchOptions[$token] }
        } elseif ($command -eq 'download' -and $token -in @('--write-subs', '--no-write-subs', '--write-auto-subs', '--no-write-auto-subs')) {
            $subtitleArgs += $token
        } elseif ($command -eq 'download' -and $token -in @('--sub-langs', '--sub-format', '--convert-subs')) {
            if (++$i -ge $tokens.Count) { throw "Missing value for $token" }
            $subtitleArgs += @($token, [string]$tokens[$i])
        } elseif ($token.StartsWith('--') -or $token -in @('-h', '-o')) {
            $forwarded += $token
            # Keep a native option's value out of the positional-output accounting.
            if ($token -in @('--input-file', '--out-root', '--language', '--resume', '--max-videos', '--yt-dlp', '--ffmpeg', '--output', '--markdown-output', '--manifest', '--max-chars', '-o')) {
                if (++$i -ge $tokens.Count) { throw "Missing value for $token" }
                $forwarded += [string]$tokens[$i]
            }
        } elseif ($token.StartsWith('-')) {
            throw "Unknown option for ${command}: $token"
        } else {
            $positionals += $token
        }
    }
    # Named positional aliases bind by identity, even when -Report precedes -Folder.
    $orderedPositionals = @()
    $inputOption = if ($command -eq 'download') { '-Url' } else { '-Folder' }
    if ($namedPositionals.ContainsKey($inputOption)) { $orderedPositionals += $namedPositionals[$inputOption] }
    elseif ($positionals.Count) { $orderedPositionals += $positionals[0]; $positionals = @($positionals | Select-Object -Skip 1) }
    if ($command -eq 'accept-report' -and $namedPositionals.ContainsKey('-Report')) { $orderedPositionals += $namedPositionals['-Report'] }
    elseif ($command -eq 'merge' -and $positionals.Count) {
        $forwarded += @('--output', $positionals[0])
        $positionals = @($positionals | Select-Object -Skip 1)
    }
    $forwarded = $orderedPositionals + $positionals + $forwarded
    if ($subtitleArgs.Count) { $forwarded += @('--subtitle-args') + $subtitleArgs }
    $pythonCommand = Get-Command -Name $python -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $helper = Join-Path $PSScriptRoot 'captions2llm.py'
    if (-not (Test-Path -LiteralPath $helper)) { throw "Python helper not found: $helper" }
    $argumentList = @('-X', 'utf8', $helper)
    if ($command) { $argumentList += $command }
    $argumentList += $forwarded
    & $pythonCommand.Source @argumentList
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 2 }
    exit $code
} catch {
    exit (Write-LaunchFailure $_.Exception.Message)
}
