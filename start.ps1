param(
    [ValidateSet("start", "stop", "logs")]
    [string]$Command = "start"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $env:TEMP "chirptype.pid"
$LogFile = Join-Path $env:TEMP "chirptype.out"
$ErrorLogFile = "$LogFile.err"

function Get-ChirpTypeProcess {
    if (-not (Test-Path $PidFile)) {
        return $null
    }

    try {
        $ProcessId = [int](Get-Content $PidFile -Raw).Trim()
        $Process = Get-Process -Id $ProcessId -ErrorAction Stop
        $ProcessInfo = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $ProcessId" `
            -ErrorAction Stop
        if ($null -eq $ProcessInfo -or $ProcessInfo.CommandLine -notmatch "chirptype\.py") {
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
            return $null
        }
        return $Process
    }
    catch {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }
}

switch ($Command) {
    "start" {
        $ExistingProcess = Get-ChirpTypeProcess
        if ($null -ne $ExistingProcess) {
            Write-Output "Already running (PID: $($ExistingProcess.Id))"
            exit 0
        }

        $Uv = Get-Command uv -ErrorAction SilentlyContinue
        if ($null -eq $Uv) {
            throw "uv was not found. Install uv, then run this script again."
        }

        $Process = Start-Process `
            -FilePath $Uv.Source `
            -ArgumentList @("run", "python", "chirptype.py", "--quiet") `
            -WorkingDirectory $ScriptDir `
            -RedirectStandardOutput $LogFile `
            -RedirectStandardError $ErrorLogFile `
            -WindowStyle Hidden `
            -PassThru

        $Process.Id | Set-Content -Path $PidFile -NoNewline
        Write-Output "Started (PID: $($Process.Id))"
    }
    "stop" {
        $Process = Get-ChirpTypeProcess
        if ($null -eq $Process) {
            Write-Output "Not running"
            exit 0
        }

        taskkill.exe /PID $Process.Id /T /F | Out-Null
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        Write-Output "Stopped"
    }
    "logs" {
        if (-not (Test-Path $LogFile)) {
            Write-Output "No output log yet."
            exit 0
        }

        Get-Content -Path @($LogFile, $ErrorLogFile) -Wait -ErrorAction SilentlyContinue
    }
}
