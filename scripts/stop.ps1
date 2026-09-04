# stop.ps1 — stop the tender-agent stack (FastAPI backend + Next.js frontend).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\stop.ps1            # both
#   powershell -ExecutionPolicy Bypass -File scripts\stop.ps1 backend    # backend only
#
# Or just double-click scripts\stop.bat.

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('all', 'backend', 'frontend')]
    [string]$Service = 'all',

    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = 'SilentlyContinue'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir   = Split-Path -Parent $ScriptDir
$RunDir    = Join-Path $RootDir '.run'

$BackendPidFile  = Join-Path $RunDir 'backend.pid'
$FrontendPidFile = Join-Path $RunDir 'frontend.pid'

function Stop-Service([string]$Name, [string]$PidFile, [int]$Port) {
    $stopped = $false

    if (Test-Path $PidFile) {
        $raw = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($raw -match '^\d+$') {
            $procId = [int]$raw
            if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
                Write-Host "▶ Stopping ${Name} (pid ${procId}) ..."
                # /T kills the child tree (uv -> uvicorn; cmd -> npm -> node -> next).
                taskkill /F /T /PID $procId 2>&1 | Out-Null
                $stopped = $true
                Write-Host "  ✓ ${Name} stopped"
            } else {
                Write-Host "${Name}: pid file present but process ${procId} not running"
            }
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    if (-not $stopped) {
        Write-Host "${Name}: no live pid — cleaning up anything on :${Port} ..."
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    }
}

switch ($Service) {
    'all'      { Stop-Service 'backend'  $BackendPidFile  $BackendPort
                 Stop-Service 'frontend' $FrontendPidFile $FrontendPort }
    'backend'  { Stop-Service 'backend'  $BackendPidFile  $BackendPort }
    'frontend' { Stop-Service 'frontend' $FrontendPidFile $FrontendPort }
}

Write-Host 'Done.'
