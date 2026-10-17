# Invoke-P51Pytest.ps1 - diagnostic wrapper for ONE child python/pytest run.
# STATUS: written but NOT yet run on Windows. Keep it separate from the existing launcher until the
# Windows test procedure has passed. Targets Windows PowerShell 5.1. Dot-source it, then call
# Invoke-P51Pytest. It never reads or prints credentials; it restores the three environment
# variables it sets. It deliberately does not call Set-StrictMode (that would leak into the caller).
#
# If anything goes wrong after the child has been launched, the original exception is re-thrown
# unchanged and the child is NOT stopped: this wrapper never terminates a process. (The child may be
# a long benchmark whose evidence would be destroyed, and nothing here can establish that stopping it
# is safe or necessary.) Restoring the environment variables below affects only this PowerShell
# process; the child keeps the copy it was started with. The run record states whether the child had
# exited, was still running, or could not be checked at the moment the wrapper stopped waiting.
# With -NoNewWindow the child shares this console, so a Ctrl+C is expected to reach the child as well
# as this wrapper; the run record, not this comment, shows what actually happened (Windows-unverified).

function Write-P51Json {
    param([string]$Path, $Object)
    $tmp = $Path + '.tmp'
    $json = $Object | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

# Start-Process joins an argument ARRAY with spaces and adds no quoting, so a single string is built
# here instead. Plain tokens pass through; anything else is wrapped in double quotes. Double quotes
# inside an argument and a trailing backslash are refused. Whether the child really receives the
# exact arguments is checked by the Windows test procedure, not assumed.
function ConvertTo-P51ArgumentString {
    param([string[]]$Arguments)
    $parts = @()
    foreach ($a in $Arguments) {
        if ($a.Length -eq 0) { throw 'P51: empty arguments are not supported' }
        if ($a.Contains('"')) { throw 'P51: arguments containing a double quote are not supported' }
        if ($a -match '^[A-Za-z0-9_\-\.:/=,\\{}@+]+$') { $parts += $a }
        elseif ($a.EndsWith('\')) { throw 'P51: a quoted argument must not end with a backslash' }
        else { $parts += ('"' + $a + '"') }
    }
    return ($parts -join ' ')
}

function Invoke-P51Pytest {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$LogDir = (Join-Path $env:LOCALAPPDATA 'cfi-p51-benchmark'),
        [string]$RunId = ((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss') + 'Z-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    )
    $argString = ConvertTo-P51ArgumentString $Arguments
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $stem = Join-Path $LogDir ('p51-pytest-' + $RunId)
    $out = $stem + '.out.log'
    $err = $stem + '.err.log'
    $runFile = $stem + '.run.json'
    # Facts the wrapper itself observed. Nothing in here is an inference.
    $rec = [ordered]@{
        kind = 'p51_launcher_run'; run_id = $RunId; wrapper_event = 'launching'; launcher_pid = $PID
        started_utc = (Get-Date).ToUniversalTime().ToString('o'); child_pid = $null; child_start_utc = $null
        child_status_at_wrapper_exit = $null; exit_code = $null; exit_code_observed = $false
        error_type = $null; note = $null; ended_utc = $null
        stdout_log = $out; stderr_log = $err; stdout_bytes = $null; stderr_bytes = $null
        pytest_summary_seen = $null
    }
    Write-P51Json $runFile $rec   # written BEFORE the child starts; a failure here stops the run

    $names = @('PYTHONUNBUFFERED', 'CFI_P51_PROGRESS_DIR', 'CFI_P51_RUN_ID')
    $saved = @{}
    foreach ($n in $names) { $saved[$n] = [Environment]::GetEnvironmentVariable($n) }
    $p = $null
    try {
        [Environment]::SetEnvironmentVariable('PYTHONUNBUFFERED', '1')
        [Environment]::SetEnvironmentVariable('CFI_P51_PROGRESS_DIR', $LogDir)
        [Environment]::SetEnvironmentVariable('CFI_P51_RUN_ID', $RunId)
        $p = Start-Process -FilePath $Python -ArgumentList $argString -WorkingDirectory $WorkingDirectory `
            -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
        $null = $p.Handle   # documented workaround: keeps the handle so ExitCode stays readable
        $rec.wrapper_event = 'child_started'
        $rec.child_pid = $p.Id
        try { $rec.child_start_utc = $p.StartTime.ToUniversalTime().ToString('o') } catch { $rec.note = 'child_start_time_unreadable' }
        try { Write-P51Json $runFile $rec } catch { $rec.note = 'run_record_update_failed' }
        Write-Host "[P51] child started (pid $($p.Id)); live output: Get-Content -Wait '$out'"
        # Poll instead of one blocking WaitForExit(): Windows PowerShell 5.1 cannot act on Ctrl+C
        # while it sits inside a single blocking .NET call.
        while (-not $p.WaitForExit(500)) { }
        $rec.wrapper_event = 'wait_returned'
    }
    catch {
        $rec.error_type = $_.Exception.GetType().Name
        throw
    }
    finally {
        # Best effort only: this block does NOT run if PowerShell is forcibly terminated, and each
        # step is isolated so that one failing step cannot hide the exception being propagated.
        try { foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $saved[$n]) } } catch { }
        # What the wrapper could observe about the child when it stopped waiting, whatever the reason
        # (normal exit, Ctrl+C, an exception): not_started | exited | still_running | could_not_check.
        $rec.child_status_at_wrapper_exit = 'not_started'
        if ($null -ne $p) {
            $rec.child_status_at_wrapper_exit = 'could_not_check'
            try {
                $p.Refresh()
                if ($p.HasExited) {
                    $rec.child_status_at_wrapper_exit = 'exited'
                    $code = $p.ExitCode
                    if ($null -ne $code) { $rec.exit_code = [int]$code; $rec.exit_code_observed = $true }
                    else { $rec.note = 'exited_but_exit_code_unavailable' }
                }
                else { $rec.child_status_at_wrapper_exit = 'still_running' }
            } catch { $rec.note = 'child_status_check_failed' }
        }
        try {
            if (Test-Path -LiteralPath $out) {
                $rec.stdout_bytes = (Get-Item -LiteralPath $out).Length
                $rec.pytest_summary_seen = [bool](Select-String -LiteralPath $out -Pattern '^(=+ )?([0-9]+ (passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?)|no tests ran)\b[^\r\n]* in [0-9.]+s' -Quiet)
            }
            if (Test-Path -LiteralPath $err) { $rec.stderr_bytes = (Get-Item -LiteralPath $err).Length }
        } catch { }
        $rec.ended_utc = (Get-Date).ToUniversalTime().ToString('o')
        try { Write-P51Json $runFile $rec } catch { Write-Host '[P51] WARNING: the run record could not be written' }
        try {
            if ($rec.child_status_at_wrapper_exit -eq 'still_running') {
                Write-Host "[P51] WARNING: the wrapper is stopping while the child (pid $($rec.child_pid)) is still running. It was NOT stopped. Restoring this window's environment variables does not affect the child, which keeps its own copy."
            }
            elseif ($rec.child_status_at_wrapper_exit -eq 'could_not_check') {
                Write-Host "[P51] WARNING: the wrapper is stopping and could not check whether the child (pid $($rec.child_pid)) is still running. It was NOT stopped."
            }
        } catch { }
        Write-Host "[P51] exit_code=$($rec.exit_code) observed=$($rec.exit_code_observed) summary_seen=$($rec.pytest_summary_seen) record=$runFile"
    }
    return [pscustomobject]@{
        ExitCode = $rec.exit_code; ExitCodeObserved = $rec.exit_code_observed
        RunFile = $runFile; StdoutLog = $out; StderrLog = $err
    }
}

function Read-P51Json {
    param([string]$Path)
    for ($i = 0; $i -lt 2; $i++) {
        try { return (Get-Content -Raw -Encoding UTF8 -LiteralPath $Path -ErrorAction Stop | ConvertFrom-Json) }
        catch { Start-Sleep -Milliseconds 200 }
    }
    return $null
}

# Read-only. Returns OBSERVED facts (what the two files and the process table say right now) and
# one CLASSIFICATION, which is an inference from them. The classification never says why a
# process ended. The launcher record and the Python checkpoint are separate files written at
# different moments; they are never assumed to agree. Remaining races: the child may exit before
# its pid is recorded; the process table is read at one instant; a pid can be reused (the start
# time is compared when it was recorded); a checkpoint can be replaced between two reads; an exit
# code of 259 (STILL_ACTIVE) is ambiguous; the summary-line match is a text heuristic.
function Get-P51RunStatus {
    param([Parameter(Mandatory = $true)][string]$RunFile)
    $r = Read-P51Json $RunFile
    if ($null -eq $r) { return [pscustomobject]@{ Classification = 'run_record_unreadable'; Observed = $null } }

    $ck = $null
    $ckName = $null
    $found = @(Get-ChildItem -LiteralPath (Split-Path -Parent $RunFile) -Filter ('p51_progress-' + $r.run_id + '*.json') -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($found.Count -gt 0) { $ckName = $found[0].Name; $ck = Read-P51Json $found[0].FullName }

    $child = 'no_pid_recorded'
    if ($r.child_pid) {
        $proc = Get-Process -Id $r.child_pid -ErrorAction SilentlyContinue
        if (-not $proc) { $child = 'no_process_with_that_pid' }
        elseif (-not $r.child_start_utc) { $child = 'pid_exists_but_start_time_was_not_recorded' }
        else {
            try {
                $delta = [math]::Abs(($proc.StartTime.ToUniversalTime() - ([datetime]$r.child_start_utc).ToUniversalTime()).TotalSeconds)
                if ($delta -lt 2) { $child = 'same_process_still_running' } else { $child = 'pid_now_belongs_to_a_different_process' }
            } catch { $child = 'pid_exists_but_its_start_time_is_unreadable' }
        }
    }
    $ckStatus = $null
    if ($null -ne $ck) { $ckStatus = $ck.status }

    $observed = [ordered]@{
        wrapper_event_last_recorded    = $r.wrapper_event
        wrapper_finally_block_reached  = [bool]$r.ended_utc
        child_status_when_wrapper_stopped = $r.child_status_at_wrapper_exit
        wrapper_error_type             = $r.error_type
        child_pid_recorded             = [bool]$r.child_pid
        exit_code_observed_by_wrapper  = [bool]$r.exit_code_observed
        exit_code                      = $r.exit_code
        pytest_summary_line_detected   = $r.pytest_summary_seen
        child_process_right_now        = $child
        python_checkpoint_file         = $ckName
        python_checkpoint_status       = $ckStatus
        python_checkpoint_updated_utc  = $(if ($null -ne $ck) { $ck.updated_utc } else { $null })
        python_checkpoint_current_stage = $(if ($null -ne $ck) { $ck.current_stage } else { $null })
    }

    if ($r.exit_code_observed) {
        if ($r.exit_code -eq 0) {
            if ($ckStatus -eq 'completed') { $class = 'exit_0_and_python_checkpoint_says_completed' }
            elseif ($null -eq $ck) { $class = 'exit_0_but_no_python_checkpoint_found' }   # e.g. skipped or deselected: not shown to have run
            else { $class = 'exit_0_but_python_checkpoint_not_completed' }
        }
        elseif ($r.exit_code -ge 1 -and $r.exit_code -le 5) { $class = 'exit_code_in_pytest_range_1_to_5' }
        else { $class = 'exit_code_outside_pytest_range_0_to_5' }
    }
    elseif ($child -eq 'same_process_still_running') { $class = 'no_exit_code_and_child_still_running' }
    else { $class = 'no_exit_code_observed_and_child_not_confirmed_running' }

    return [pscustomobject]@{
        Classification = $class
        Observed = $observed
        Note = 'Classification is an inference from the observed facts. It does not state why any process ended.'
    }
}
