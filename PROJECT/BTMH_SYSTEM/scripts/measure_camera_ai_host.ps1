# Read-only resource sampling. No DB, credentials, command lines or configuration.
[CmdletBinding()]
param(
    [ValidateRange(1, 120)][int]$Seconds = 30,
    [ValidateRange(100, 10000)][int]$IntervalMs = 1000,
    [ValidateRange(1, 65535)][int]$Port = 8100,
    [int]$BackendProcessId = 0
)
$ErrorActionPreference = 'Stop'
if (-not $BackendProcessId) {
    try {
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique)
        if ($listeners.Count -ne 1) { throw 'LISTENER_NOT_UNIQUE' }
        $BackendProcessId = [int]$listeners[0]
    } catch {
        Write-Output '{"status":"BACKEND_PID_UNAVAILABLE","hint":"Use -BackendProcessId with the existing web server PID; no credentials needed."}'
        exit 1
    }
}
$previous = @{}
$samples = [System.Collections.Generic.List[object]]::new()
$logicalCpus = [Environment]::ProcessorCount
$clock = [Diagnostics.Stopwatch]::StartNew()
while ($clock.Elapsed.TotalSeconds -lt $Seconds) {
    $at = $clock.Elapsed.TotalSeconds
    try {
        # Request only safe process properties; never request CommandLine.
        $rows = @(Get-CimInstance Win32_Process -Property Name, ProcessId, ParentProcessId)
        $family = [System.Collections.Generic.HashSet[int]]::new()
        [void]$family.Add($BackendProcessId)
        do {
            $changed = $false
            foreach ($row in $rows) {
                if ($family.Contains([int]$row.ParentProcessId) -and $family.Add([int]$row.ProcessId)) { $changed = $true }
            }
        } while ($changed)
        $items = [System.Collections.Generic.List[object]]::new()
        foreach ($processIdValue in $family) {
            $process = Get-Process -Id $processIdValue -ErrorAction SilentlyContinue
            if (-not $process) { continue }
            $cpu = $process.TotalProcessorTime.TotalSeconds
            $percent = $null
            $old = $previous[$processIdValue]
            if ($old -and $process.StartTime.Ticks -eq $old.Start -and $at -gt $old.At) {
                $percent = [Math]::Round([Math]::Max(0, ($cpu - $old.Cpu) / ($at - $old.At) / $logicalCpus * 100), 2)
            }
            $previous[$processIdValue] = @{Cpu=$cpu; At=$at; Start=$process.StartTime.Ticks}
            $items.Add([pscustomobject]@{pid=$processIdValue; name=$process.ProcessName;
                cpu_percent_of_host=$percent; working_set_mb=[Math]::Round($process.WorkingSet64/1MB,2);
                private_memory_mb=[Math]::Round($process.PrivateMemorySize64/1MB,2); threads=$process.Threads.Count})
        }
        $samples.Add([pscustomobject]@{elapsed_sec=[Math]::Round($at,3); processes=@($items.ToArray())})
    } catch {
        $samples.Add([pscustomobject]@{elapsed_sec=[Math]::Round($at,3); error_code='PROCESS_SAMPLE_UNAVAILABLE'})
    }
    $remainingMs = [int][Math]::Max(0, ($Seconds - $clock.Elapsed.TotalSeconds) * 1000)
    if ($remainingMs -gt 0) { Start-Sleep -Milliseconds ([Math]::Min($IntervalMs,$remainingMs)) }
}
[pscustomobject]@{status='READ_ONLY_SAMPLES'; backend_pid=$BackendProcessId; logical_cpus=$logicalCpus;
    cpu_normalization='percent of all logical CPUs'; gpu='NOT_MEASURED';
    note='Process resources do not establish recognition accuracy, inference provider, or camera FPS.';
    samples=@($samples.ToArray())} | ConvertTo-Json -Depth 6
