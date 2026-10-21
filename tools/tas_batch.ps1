# Runs the gameplay TAS scripts in tools/tas at 30 and 60 fps (low impact) and prints each
# result; logs and telemetry go to out/tas. Scripts that only dump memory (find_*) and the
# shared boot prefix are skipped. Compare speed_30.csv with speed_60.csv (see docs/tas.md).
#   powershell -ExecutionPolicy Bypass -File tools/tas_batch.ps1 [-Filter speed] [-Rates 30,60] [-Full]
param([string]$Filter = "*", [int[]]$Rates = @(30, 60), [switch]$Full)
foreach ($s in Get-ChildItem (Join-Path $PSScriptRoot "tas\$Filter.tas")) {
    if ($s.BaseName -like "find_*" -or $s.BaseName -eq "boot_stage1") { continue }
    foreach ($fps in $Rates) {
        $args = @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "tas_run.ps1"), "-Script", $s.FullName, "-Seconds", "300")
        if ($fps -eq 60) { $args += "-Fps60" }
        if ($Full) { $args += "-Full" }
        $r = & powershell @args
        "$(Get-Date -Format HH:mm) $($r -join ' ')"
    }
}
