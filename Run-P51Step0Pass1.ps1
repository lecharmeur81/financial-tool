# Run-P51Step0Pass1.ps1
# Phase 51 Step 0, Pass 1: EXPLAIN-only diagnostic wrapper (14 reviewed statements).
# Run as a file:  powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-P51Step0Pass1.ps1
# Exit codes: 0 success | 1 preflight failure (container never launched) | 2 container/report failure | 3 unexpected wrapper error
# The script takes no parameters, sets no session environment variables, and prints no credentials.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- fixed configuration
$BaseDir     = 'E:\p51_step0'
$WorkDir     = 'E:\p51_step0\work'
$OutRoot     = 'E:\p51_step0\out'
$ProjectDir  = 'E:\FINANCIAL TOOL'
$ImageTag    = 'cfi-backend:p50-census'
$ImageId     = 'sha256:b23b13492d47a7adb2bc643ad487d0fe7128557925d1aac233e3e82e96640a6e'
$Network     = 'cfi_default'
$ApiName     = 'cfi-api-1'
$MemLimit    = '2g'
$PidsLimit   = '128'
$RunTimeoutSec = 300
$PartialName = 'p51_step0_pass1.partial.txt'
$FinalName   = 'p51_step0_pass1_plans.txt'
$DoneLine    = 'DONE (valid only if the process exit code is 0): all statements EXPLAINed; nothing executed, nothing committed.'
$ExpectedIds = @('Q0','Q0b','Q1','Q1b','Q2','Q3a','Q3b','Q3c','Q4','Q5a','Q5b','Q5c','Q6','Q7')
$ExpectedHashes = [ordered]@{
    'p51_step0_runner.py'     = '71e4d5eb278da1ddc1e81ba0f58176fe1c525c8dc5aceee54bc496a2ff7ac98d'
    'p51_step0_statements.py' = 'c052a97331a4f8341dd890e9e904a18ecd2a95ad8561f839b4da61b51a5becee'
    'phase50_census.py'       = '67d3be9f1d85a21d5a3190c0d866d16f7df19641d94c6650cfa80eaa0c28345c'
}
$UrlPattern  = '^postgresql\+psycopg://[^/@\s]*@db(?::5432)?/cfi$'

# ---------------------------------------------------------------- state touched by cleanup
$script:Code      = 3
$script:DbUrl     = $null
$script:Psi       = $null
$script:ContainerName = $null
$script:RunStarted = $false
$script:RunCompleted = $false
$script:Proc      = $null
$script:DockerExe = $null
$script:DockerContext = $null
$AttemptDir       = $null

# Docker endpoint policy: only these context names, and only these local named-pipe endpoints, are accepted.
$AllowedContexts  = @('default', 'desktop-linux')
$AllowedEndpoints = @('npipe:////./pipe/docker_engine', 'npipe:////./pipe/dockerDesktopLinuxEngine')

# Variable names the verified image may define. Anything else stops the run before launch (names are shown, values never are).
# CFI_DATABASE_URL, CFI_REDIS_URL, CFI_ENVIRONMENT and PYTHONPATH/PYTHONDONTWRITEBYTECODE are allowed only because the
# wrapper overrides each of them explicitly with -e (an explicit -e always wins over image ENV).
$AllowedImageEnvNames = @(
    'PATH', 'LANG', 'LC_ALL', 'GPG_KEY', 'PYTHON_VERSION', 'PYTHON_SHA256', 'PYTHON_PIP_VERSION', 'PYTHON_SETUPTOOLS_VERSION',
    'PYTHON_GET_PIP_URL', 'PYTHON_GET_PIP_SHA256', 'PYTHONUNBUFFERED', 'UV_COMPILE_BYTECODE', 'UV_LINK_MODE', 'UV_PROJECT_ENVIRONMENT',
    'PYTHONDONTWRITEBYTECODE', 'PYTHONPATH', 'CFI_DATABASE_URL', 'CFI_REDIS_URL', 'CFI_ENVIRONMENT'
)

function Say([string]$m) { Write-Host ('[P51] ' + $m) }
function PreFail([string]$m) { throw (New-Object System.InvalidOperationException('P51PRE:' + $m)) }
function RunFail([string]$m) { throw (New-Object System.InvalidOperationException('P51RUN:' + $m)) }

function Quote-Arg([string]$a) {
    if ($a.Contains('"')) { throw (New-Object System.ArgumentException('P51 internal: double quote in argument')) }
    if ($a -match '^[A-Za-z0-9_\-\.:/=,\\{}@+]+$') { return $a }
    return '"' + $a + '"'
}

# Runs a native program with explicit exit-code capture. Environment is passed only through the ProcessStartInfo
# (never the session). Output is returned, never echoed.
function Invoke-Native {
    param([string]$Exe, [string[]]$ArgList, [int]$TimeoutSec, [hashtable]$ExtraEnv, [string]$KillName)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = (($ArgList | ForEach-Object { Quote-Arg $_ }) -join ' ')
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.CreateNoWindow = $true
    foreach ($k in @($psi.EnvironmentVariables.Keys)) {
        if ($k -like 'CFI_*' -or $k -like 'PG*' -or $k -like 'PYTHON*') { $psi.EnvironmentVariables.Remove($k) }
    }
    if ($ExtraEnv) { foreach ($k in $ExtraEnv.Keys) { $psi.EnvironmentVariables[$k] = [string]$ExtraEnv[$k] } }
    $prevPsi = $script:Psi
    $prevProc = $script:Proc
    $script:Psi = $psi
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    $null = $p.Start()
    $script:Proc = $p
    $p.StandardInput.Close()
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    $timedOut = $false
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
        $timedOut = $true
        if ($KillName) { try { $null = Invoke-Native -Exe $Exe -ArgList (Docker-Args @('kill', $KillName)) -TimeoutSec 30 -ExtraEnv $null -KillName $null } catch { } }
        if (-not $p.WaitForExit(30000)) { try { $p.Kill() } catch { } }
    }
    $p.WaitForExit()
    $result = [pscustomobject]@{
        ExitCode = $p.ExitCode
        Stdout   = $outTask.Result
        Stderr   = $errTask.Result
        TimedOut = $timedOut
    }
    $p.Dispose()
    $script:Proc = $prevProc
    $script:Psi = $prevPsi
    return $result
}

# Every daemon-facing docker call is pinned to the verified context with the global --context flag, so the
# endpoint cannot change between verification and use.
function Docker-Args([string[]]$ArgList) {
    if (-not $script:DockerContext) { throw (New-Object System.InvalidOperationException('P51PRE:docker context not established')) }
    return @('--context', $script:DockerContext) + $ArgList
}

# Client-side only calls (docker context ...): no daemon connection, no context pin.
function Docker-Raw([string[]]$ArgList) {
    $r = Invoke-Native -Exe $script:DockerExe -ArgList $ArgList -TimeoutSec 60 -ExtraEnv $null -KillName $null
    if ($r.TimedOut -or $r.ExitCode -ne 0) { PreFail ('docker ' + $ArgList[0] + ' ' + $ArgList[1] + ' failed (exit ' + $r.ExitCode + ', timed out: ' + $r.TimedOut + ')') }
    return $r.Stdout.Trim()
}

function Docker-Quick([string[]]$ArgList) {
    $r = Invoke-Native -Exe $script:DockerExe -ArgList (Docker-Args $ArgList) -TimeoutSec 60 -ExtraEnv $null -KillName $null
    if ($r.TimedOut -or $r.ExitCode -ne 0) { PreFail ('docker ' + $ArgList[0] + ' ' + $ArgList[1] + ' failed (exit ' + $r.ExitCode + ', timed out: ' + $r.TimedOut + ')') }
    return $r.Stdout.Trim()
}

function Assert-PlainDir([string]$Path, [string]$What) {
    if ($Path -ne [System.IO.Path]::GetFullPath($Path)) { PreFail ($What + ' path is not normalised') }
    if ($Path -match '[\s,"''`;&|<>^%]') { PreFail ($What + ' path contains characters that are not allowed') }
    if ($Path.StartsWith($ProjectDir, [System.StringComparison]::OrdinalIgnoreCase)) { PreFail ($What + ' lies inside the project directory') }
    $d = New-Object System.IO.DirectoryInfo($Path)
    if (-not $d.Exists) { PreFail ($What + ' directory does not exist') }
    if (($d.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { PreFail ($What + ' directory is a reparse point') }
}

function Get-WorkHashProblem {
    $d = New-Object System.IO.DirectoryInfo($WorkDir)
    $items = @($d.GetFileSystemInfos())
    if ($items.Count -ne $ExpectedHashes.Count) { return 'work directory does not contain exactly 3 entries' }
    foreach ($it in $items) {
        if ($it -isnot [System.IO.FileInfo]) { return 'work directory contains a non-file entry' }
        if (($it.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return 'work directory contains a reparse point' }
        if (-not $ExpectedHashes.Contains($it.Name)) { return 'work directory contains an unexpected file name' }
    }
    foreach ($name in $ExpectedHashes.Keys) {
        $f = Join-Path $WorkDir $name
        if (-not [System.IO.File]::Exists($f)) { return ('missing work file ' + $name) }
        $h = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($h -cne $ExpectedHashes[$name]) { return ('SHA-256 mismatch for ' + $name) }
    }
    return $null
}

function New-TextFileNoOverwrite([string]$Path, [string]$Text) {
    $fs = New-Object System.IO.FileStream($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text)
        $fs.Write($bytes, 0, $bytes.Length)
        $fs.Flush($true)
    } finally { $fs.Dispose() }
}

try {
    # ------------------------------------------------------------ 1. preflight (no container is launched until all pass)
    # 1a. Docker endpoint: no DOCKER_* override of any kind, a named local context, a local named-pipe endpoint.
    $dockerVars = @(Get-ChildItem -Path Env: | Where-Object { $_.Name -like 'DOCKER_*' } | ForEach-Object { $_.Name })
    if ($dockerVars.Count -gt 0) { PreFail ('DOCKER_* environment variable(s) set (' + ($dockerVars -join ', ') + '); refusing to use an overridden Docker endpoint') }
    $cmd = @(Get-Command -Name 'docker' -CommandType Application -ErrorAction SilentlyContinue)
    if ($cmd.Count -lt 1) { PreFail 'docker executable not found' }
    $script:DockerExe = $cmd[0].Source

    $ctxName = Docker-Raw @('context', 'show')
    if ($AllowedContexts -cnotcontains $ctxName) { PreFail 'active Docker context is not one of the allowed local contexts (default, desktop-linux); not switching it' }
    $ctxHost = Docker-Raw @('context', 'inspect', $ctxName, '--format', '{{.Endpoints.docker.Host}}')
    if ($AllowedEndpoints -cnotcontains $ctxHost) { PreFail 'Docker context endpoint is not an allowed local named pipe (docker_engine or dockerDesktopLinuxEngine)' }
    $script:DockerContext = $ctxName
    Say ('docker context "' + $ctxName + '" resolves to an allowed local endpoint; all docker calls are pinned to it')

    Assert-PlainDir $BaseDir 'base'
    Assert-PlainDir $WorkDir 'work'
    Assert-PlainDir $OutRoot 'output root'

    $problem = Get-WorkHashProblem
    if ($problem) { PreFail $problem }
    Say 'work files: exactly 3 files, SHA-256 verified'

    $imgId = Docker-Quick @('image', 'inspect', $ImageTag, '--format', '{{.Id}}')
    if ($imgId -cne $ImageId) { PreFail ('image ' + $ImageTag + ' does not have the expected ID') }
    Say 'image identity verified (will be run by ID, never pulled or rebuilt)'

    # 1b. Image configuration: only allow-listed environment names; no entrypoint. Values are discarded unread.
    $imgEnvJson = Docker-Quick @('image', 'inspect', $ImageId, '--format', '{{json .Config.Env}}')
    $imgEnvNames = @(ConvertFrom-Json -InputObject $imgEnvJson | Where-Object { $_ -is [string] } | ForEach-Object {
        $i = $_.IndexOf('=')
        if ($i -lt 0) { $_ } else { $_.Substring(0, $i) }
    })
    $imgEnvJson = $null
    $badNames = @($imgEnvNames | Where-Object { $AllowedImageEnvNames -cnotcontains $_ } | Select-Object -Unique)
    if ($badNames.Count -gt 0) { PreFail ('image defines environment variable name(s) outside the allow-list: ' + ($badNames -join ', ') + ' (values not read); review before any run') }
    $imgEntry = Docker-Quick @('image', 'inspect', $ImageId, '--format', '{{json .Config.Entrypoint}}')
    if ($imgEntry -cne 'null' -and $imgEntry -cne '[]') { PreFail 'image defines an ENTRYPOINT; refusing to run behind an unreviewed wrapper' }
    Say ('image environment: ' + $imgEnvNames.Count + ' variable name(s), all allow-listed; no entrypoint')

    $netName = Docker-Quick @('network', 'inspect', $Network, '--format', '{{.Name}}')
    if ($netName -cne $Network) { PreFail ('network ' + $Network + ' not found') }

    $running = Docker-Quick @('inspect', $ApiName, '--format', '{{.State.Running}}')
    if ($running -cne 'true') { PreFail ('container ' + $ApiName + ' is not running') }

    $envJson = Docker-Quick @('inspect', $ApiName, '--format', '{{json .Config.Env}}')
    $envList = @(ConvertFrom-Json -InputObject $envJson | Where-Object { $_ -is [string] })
    $envJson = $null
    $urlEntries = @($envList | Where-Object { $_.StartsWith('CFI_DATABASE_URL=', [System.StringComparison]::Ordinal) })
    if ($urlEntries.Count -ne 1) { PreFail 'API container does not define CFI_DATABASE_URL exactly once' }
    $script:DbUrl = $urlEntries[0].Substring('CFI_DATABASE_URL='.Length)
    if ($script:DbUrl -cnotmatch $UrlPattern) { PreFail 'database URL does not match the required form (psycopg driver, host db, database cfi, no query)' }
    $envEntries = @($envList | Where-Object { $_.StartsWith('CFI_ENVIRONMENT=', [System.StringComparison]::Ordinal) })
    if ($envEntries.Count -gt 1) { PreFail 'API container defines CFI_ENVIRONMENT more than once' }
    if ($envEntries.Count -eq 1 -and $envEntries[0] -cne 'CFI_ENVIRONMENT=development') { PreFail 'API container CFI_ENVIRONMENT is not development' }
    $runtimeDefined = (@($envList | Where-Object { $_.StartsWith('CFI_DATABASE_URL_RUNTIME=', [System.StringComparison]::Ordinal) })).Count -gt 0
    $envList = $null
    $urlEntries = $null
    Say ('database URL validated without display (host db, database cfi, development); API container defines CFI_DATABASE_URL_RUNTIME: ' + $runtimeDefined + ' (never passed on)')

    # ------------------------------------------------------------ 2. unique attempt directory (never reuses or overwrites)
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $attemptId = 'p51s0-' + $stamp + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $AttemptDir = Join-Path $OutRoot $attemptId
    $ReportDir  = Join-Path $AttemptDir 'report'
    if ([System.IO.Directory]::Exists($AttemptDir) -or [System.IO.File]::Exists($AttemptDir)) { PreFail 'attempt directory already exists' }
    $null = [System.IO.Directory]::CreateDirectory($AttemptDir)
    $null = [System.IO.Directory]::CreateDirectory($ReportDir)
    $script:ContainerName = $attemptId
    $PartialHost = Join-Path $ReportDir $PartialName
    $FinalHost   = Join-Path $ReportDir $FinalName
    $StderrHost  = Join-Path $AttemptDir 'container.stderr.txt'
    $StdoutHost  = Join-Path $AttemptDir 'container.stdout.txt'
    $ValidationHost = Join-Path $AttemptDir 'VALIDATION.txt'
    $FailedHost  = Join-Path $AttemptDir 'FAILED.txt'
    Say ('attempt directory: ' + $AttemptDir)

    # ------------------------------------------------------------ 3. run the diagnostic container
    $runArgs = @(
        'run', '--rm', '--pull=never',
        '--name', $script:ContainerName,
        '--network', $Network,
        '--read-only',
        '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges',
        '--memory', $MemLimit, '--memory-swap', $MemLimit,
        '--pids-limit', $PidsLimit,
        '-e', 'CFI_DATABASE_URL',
        '-e', 'CFI_REDIS_URL=redis://unused.invalid:6379/0',
        '-e', 'CFI_ENVIRONMENT=development',
        '-e', 'PYTHONPATH=/work',
        '-e', 'PYTHONDONTWRITEBYTECODE=1',
        '--mount', ('type=bind,source=' + $WorkDir + ',target=/work,readonly'),
        '--mount', ('type=bind,source=' + $ReportDir + ',target=/out'),
        $ImageId,
        'python', '-B', '/work/p51_step0_runner.py', 'explain', ('/out/' + $PartialName)
    )
    $script:RunStarted = $true
    Say 'launching the EXPLAIN-only container'
    $run = Invoke-Native -Exe $script:DockerExe -ArgList (Docker-Args $runArgs) -TimeoutSec $RunTimeoutSec -ExtraEnv @{ 'CFI_DATABASE_URL' = $script:DbUrl } -KillName $script:ContainerName
    $script:DbUrl = $null
    $script:RunStarted = $false
    $script:RunCompleted = $true

    New-TextFileNoOverwrite $StderrHost $run.Stderr
    if ($run.Stdout.Length -gt 0) { New-TextFileNoOverwrite $StdoutHost $run.Stdout }

    # ------------------------------------------------------------ 4. classify (all conditions must hold)
    $reasons = New-Object System.Collections.Generic.List[string]
    if ($run.TimedOut) { $reasons.Add('container exceeded the wall-clock limit and was killed') }
    if ($run.ExitCode -ne 0) { $reasons.Add('container exit code ' + $run.ExitCode + ' (expected 0)') }
    if ($run.Stderr.Length -gt 0) { $reasons.Add('container wrote to stderr (' + $run.Stderr.Length + ' characters; see container.stderr.txt)') }
    if ($run.Stdout.Length -gt 0) { $reasons.Add('container wrote to stdout (see container.stdout.txt)') }

    $reportText = $null
    if (-not [System.IO.File]::Exists($PartialHost)) {
        $reasons.Add('partial report file does not exist')
    } else {
        try { $reportText = [System.IO.File]::ReadAllText($PartialHost, (New-Object System.Text.UTF8Encoding($false, $true))) }
        catch { $reasons.Add('partial report is not readable as UTF-8') }
    }
    if ($null -ne $reportText) {
        $lines = @($reportText -split "`n" | ForEach-Object { $_.TrimEnd("`r") })
        $nonEmpty = @($lines | Where-Object { $_.Length -gt 0 })
        if ($nonEmpty.Count -eq 0) { $reasons.Add('report is empty') }
        else {
            if ($nonEmpty[0] -cnotmatch '^identity: db=cfi session_default_read_only=on revision=\S+$') { $reasons.Add('identity line missing or unexpected') }
            $doneCount = @($lines | Where-Object { $_ -ceq $DoneLine }).Count
            if ($doneCount -ne 1) { $reasons.Add('expected DONE marker count is ' + $doneCount + ' (expected 1)') }
            if ($nonEmpty[$nonEmpty.Count - 1] -cne $DoneLine) { $reasons.Add('DONE marker is not the last non-empty line') }
            if (@($lines | Where-Object { $_ -cmatch '^(ABORTED|FAILED) \(' }).Count -gt 0) { $reasons.Add('report contains an ABORTED or FAILED marker') }
            $ids = @($lines | Where-Object { $_ -cmatch '^=== Q' } | ForEach-Object { if ($_ -cmatch '^=== (Q\d+[a-c]?)(\s|$)') { $Matches[1] } else { '?' } })
            if (($ids -join ',') -cne ($ExpectedIds -join ',')) { $reasons.Add('statement sections do not equal the 14 expected, in order') }
        }
    }
    $names = @([System.IO.Directory]::GetFileSystemEntries($ReportDir) | ForEach-Object { [System.IO.Path]::GetFileName($_) })
    if ($names.Count -ne 1 -or $names[0] -cne $PartialName) { $reasons.Add('report directory does not contain exactly the partial report') }
    $problem = Get-WorkHashProblem
    if ($problem) { $reasons.Add('work files changed during the run: ' + $problem) }

    # ------------------------------------------------------------ 5. pre-promotion bookkeeping (everything required for success is finished BEFORE the move)
    # The DONE marker is only one of the checks above; success is decided by $reasons.Count -eq 0, never by the marker.
    $partialSha = $null
    $partialBytes = -1
    if ($reasons.Count -eq 0) {
        if ([System.IO.File]::Exists($FinalHost) -or [System.IO.Directory]::Exists($FinalHost)) {
            $reasons.Add('final report name already exists; no-overwrite rule prevents promotion')
        } else {
            try {
                $partialSha = (Get-FileHash -LiteralPath $PartialHost -Algorithm SHA256).Hash.ToLowerInvariant()
                $partialBytes = (New-Object System.IO.FileInfo($PartialHost)).Length
                New-TextFileNoOverwrite $ValidationHost ("VALIDATED (promotion not yet performed when this file was written)`r`n" +
                    "exit code 0; stderr and stdout empty; identity line ok; single DONE marker is last; no ABORTED/FAILED; 14 expected sections in order; work files unchanged`r`n" +
                    "partial report: report\" + $PartialName + "`r`nsha256: " + $partialSha + "`r`nbytes: " + $partialBytes + "`r`ntarget: report\" + $FinalName + "`r`n")
            } catch { $reasons.Add('pre-promotion bookkeeping failed (' + $_.Exception.GetType().Name + ')') }
        }
    }

    # ------------------------------------------------------------ 6. promotion (no-overwrite move) and verification
    if ($reasons.Count -eq 0) {
        try { [System.IO.File]::Move($PartialHost, $FinalHost) }
        catch { $reasons.Add('no-overwrite promotion failed (' + $_.Exception.GetType().Name + ')') }
        if ($reasons.Count -eq 0) {
            try {
                if (-not [System.IO.File]::Exists($FinalHost)) { $reasons.Add('final report missing after promotion') }
                elseif ([System.IO.File]::Exists($PartialHost)) { $reasons.Add('partial report still present after promotion') }
                elseif ((New-Object System.IO.FileInfo($FinalHost)).Length -ne $partialBytes -or
                        (Get-FileHash -LiteralPath $FinalHost -Algorithm SHA256).Hash.ToLowerInvariant() -cne $partialSha) {
                    $reasons.Add('final report differs from the validated partial report')
                }
            } catch { $reasons.Add('post-promotion verification failed (' + $_.Exception.GetType().Name + ')') }
        }
    }

    # ------------------------------------------------------------ 7. outcome
    if ($reasons.Count -gt 0) {
        foreach ($r in $reasons) { Say ('FAIL: ' + $r) }
        try {
            New-TextFileNoOverwrite $FailedHost ("FAILED`r`n" + (($reasons | ForEach-Object { '- ' + $_ }) -join "`r`n") +
                "`r`nArtifacts preserved; no existing file was overwritten or deleted. A report may exist under report\ only if the failure occurred after the move; see the reasons above.`r`n")
        } catch { Say 'could not write FAILED.txt; reasons are listed above' }
        Say ('artifacts preserved in ' + $AttemptDir)
        $script:Code = 2
    } else {
        Say ('SUCCESS: exit code 0 and all validation passed; report promoted to ' + $FinalHost)
        $script:Code = 0
    }
}
catch {
    $m = $_.Exception.Message
    if ($m.StartsWith('P51PRE:', [System.StringComparison]::Ordinal)) { Say ('PREFLIGHT FAILED: ' + $m.Substring(7)); $script:Code = 1 }
    elseif ($m.StartsWith('P51RUN:', [System.StringComparison]::Ordinal)) { Say ('FAILED: ' + $m.Substring(7)); $script:Code = 2 }
    elseif ($script:RunStarted -or $script:RunCompleted) {
        Say ('UNEXPECTED ERROR after the container was launched (' + $_.Exception.GetType().Name + '); artifacts preserved, run NOT successful')
        $script:Code = 2
        if ($AttemptDir) {
            try { New-TextFileNoOverwrite (Join-Path $AttemptDir 'FAILED.txt') ("FAILED`r`nunexpected error after launch (" + $_.Exception.GetType().Name + "). Artifacts preserved.`r`n") } catch { }
        }
    }
    else { Say ('UNEXPECTED ERROR (' + $_.Exception.GetType().Name + ')'); $script:Code = 3 }
}
finally {
    $script:DbUrl = $null
    try {
        if ($script:Proc -ne $null -and -not $script:Proc.HasExited -and $script:ContainerName) {
            try { $null = Invoke-Native -Exe $script:DockerExe -ArgList (Docker-Args @('kill', $script:ContainerName)) -TimeoutSec 30 -ExtraEnv $null -KillName $null } catch { }
            try { if (-not $script:Proc.HasExited) { $script:Proc.Kill() } } catch { }
        }
    } catch { }
    try {
        if ($script:Psi -ne $null) { $null = $script:Psi.EnvironmentVariables.Remove('CFI_DATABASE_URL') }
    } catch { }
    $script:Psi = $null
}
exit $script:Code
