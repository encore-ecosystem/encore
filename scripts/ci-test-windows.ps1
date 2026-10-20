param(
    [Parameter(Mandatory)][string] $Compiler,
    [Parameter(Mandatory)][string] $Report,
    [string] $ArgumentsJson = '[]',
    [ValidateRange(1, 86400)][int] $TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'

# A test owns its complete process tree (including compilers and native probes).
# Kill only isolated test workers, so Encore can record failure and finish its
# report. The workflow supplies a separate deadline for the complete suite.
function Stop-TestTree($Worker) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($Worker.ProcessId)"
    if ($null -ne $current -and $current.CreationDate -eq $Worker.CreationDate) {
        & taskkill.exe /PID $Worker.ProcessId /T /F | Out-Host
        # A worker can exit between the identity check and taskkill.
        if ($LASTEXITCODE -ne 0) {
            $remaining = Get-CimInstance Win32_Process -Filter "ProcessId = $($Worker.ProcessId)"
            if ($null -ne $remaining -and $remaining.CreationDate -eq $Worker.CreationDate) {
                throw "Could not terminate timed-out test process $($Worker.ProcessId)"
            }
        }
    }
}

$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $Compiler
$startInfo.UseShellExecute = $false
$startInfo.WorkingDirectory = (Get-Location).Path
foreach ($argument in @('test', '--report', $Report)) {
    $startInfo.ArgumentList.Add($argument)
}
foreach ($argument in (ConvertFrom-Json -InputObject $ArgumentsJson)) {
    $startInfo.ArgumentList.Add([string] $argument)
}

$process = [System.Diagnostics.Process]::new()
$process.StartInfo = $startInfo
$timedOut = [System.Collections.Generic.HashSet[string]]::new()
$started = $false
try {
    if (-not $process.Start()) { throw 'Could not start the Encore test runner' }
    $started = $true
    $rootStarted = $process.StartTime.ToUniversalTime()
    while (-not $process.WaitForExit(3000)) {
        $snapshot = @(Get-CimInstance Win32_Process)
        $descendants = @{}
        $descendants[[uint32] $process.Id] = $rootStarted
        do {
            $added = $false
            foreach ($candidate in $snapshot) {
                $id = [uint32] $candidate.ProcessId
                $parent = [uint32] $candidate.ParentProcessId
                if (-not $descendants.ContainsKey($id) -and $descendants.ContainsKey($parent) -and
                    $candidate.CreationDate.ToUniversalTime() -ge $descendants[$parent]) {
                    $descendants[$id] = $candidate.CreationDate.ToUniversalTime()
                    $added = $true
                }
            }
        } while ($added)

        foreach ($candidate in $snapshot) {
            if (-not $descendants.ContainsKey([uint32] $candidate.ProcessId)) { continue }
            $isolated = $candidate.Name -eq '__encore_unit_harness.exe' -or
                ($candidate.Name -eq 'encore.exe' -and
                 $candidate.CommandLine -match '(?:^|\s)"?--_worker-(?:standalone|harness)"?(?:\s|$)')
            if (-not $isolated) { continue }
            $age = ([DateTime]::UtcNow - $candidate.CreationDate.ToUniversalTime()).TotalSeconds
            $key = "$($candidate.ProcessId):$($candidate.CreationDate.Ticks)"
            if ($age -ge $TimeoutSeconds -and $timedOut.Add($key)) {
                [Console]::Error.WriteLine("::error::Test exceeded ${TimeoutSeconds}s: $($candidate.CommandLine)")
                Stop-TestTree $candidate
            }
        }
    }
    $code = $process.ExitCode
    if ($timedOut.Count -gt 0) { $code = 1 }
} finally {
    if ($started -and -not $process.HasExited) {
        & taskkill.exe /PID $process.Id /T /F | Out-Host
        if (-not $process.WaitForExit(10000)) {
            [Console]::Error.WriteLine('Could not terminate the Encore test runner')
        }
    }
    $process.Dispose()
}
exit $code
