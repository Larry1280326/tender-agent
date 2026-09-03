# start.ps1 — start the tender-agent stack (FastAPI backend + Next.js frontend).
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1             # both
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1 backend     # backend only
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Prod      # production mode
#
# Or just double-click scripts\start.bat.

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('all', 'backend', 'frontend')]
    [string]$Service = 'all',

    [string]$Host = '127.0.0.1',
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$Prod
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir   = Split-Path -Parent $ScriptDir
$RunDir    = Join-Path $RootDir '.run'
$LogDir    = Join-Path $RunDir 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$BackendPidFile  = Join-Path $RunDir 'backend.pid'
$FrontendPidFile = Join-Path $RunDir 'frontend.pid'

function Test-ProcessRunning([string]$PidFile) {
    if (-not (Test-Path $PidFile)) { return $false }
    $raw = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($raw -match '^\d+$') {
        return [bool](Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue)
    }
    return $false
}

# Check raw TCP connectivity only — the backend root returns 404, so a plain
# HTTP request would look "not ready" even when uvicorn is up.
function Wait-ForPort([int]$Port, [string]$Name, [int]$Attempts = 40) {
    for ($i = 0; $i -lt $Attempts; $i++) {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $result = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
            if ($result.AsyncWaitHandle.WaitOne(1000) -and $client.Connected) {
                Write-Host "  ✓ ${Name} ready on http://localhost:${Port}"
                return
            }
        } catch {
            # not up yet — try again
        } finally {
            $client.Close()
        }
        Start-Sleep -Seconds 1
    }
    Write-Warning "  ${Name} did not respond on :${Port} within ${Attempts}s — see ${LogDir}\${Name}.log"
}

function Start-Backend {
    if (Test-ProcessRunning $BackendPidFile) {
        Write-Host "backend already running (pid $(Get-Content $BackendPidFile))"
        return
    }
    Write-Host "▶ Starting backend on http://localhost:${BackendPort} ..."

    $args = @('run', 'uvicorn', 'app.main:app', '--host', $Host, '--port', "$BackendPort")
    if (-not $Prod) { $args += '--reload' }

    $proc = Start-Process -FilePath 'uv' `
        -ArgumentList $args `
        -WorkingDirectory (Join-Path $RootDir 'backend') `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'backend.log') `
        -RedirectStandardError  (Join-Path $LogDir 'backend.err.log') `
        -PassThru

    Set-Content -Path $BackendPidFile -Value $proc.Id -Encoding Ascii
    Write-Host "  backend pid $($proc.Id)"
    Wait-ForPort $BackendPort 'backend'
}

function Start-Frontend {
    if (Test-ProcessRunning $FrontendPidFile) {
        Write-Host "frontend already running (pid $(Get-Content $FrontendPidFile))"
        return
    }
    Write-Host "▶ Starting frontend on http://localhost:${FrontendPort} ..."

    $npmScript = if ($Prod) { 'start' } else { 'dev' }
    if ($Prod) { Write-Host "  (PROD mode: assuming 'npm run build' has already been run)" }

    # npm is npm.cmd — launch via cmd.exe so stop.ps1 can kill the whole tree
    # (cmd -> npm -> node -> next) with taskkill /T.
    $cmdArgs = "/c npm run $npmScript -- -p $FrontendPort"
    $proc = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList $cmdArgs `
        -WorkingDirectory (Join-Path $RootDir 'frontend') `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'frontend.log') `
        -RedirectStandardError  (Join-Path $LogDir 'frontend.err.log') `
        -PassThru

    Set-Content -Path $FrontendPidFile -Value $proc.Id -Encoding Ascii
    Write-Host "  frontend pid $($proc.Id)"
    Wait-ForPort $FrontendPort 'frontend'
}

switch ($Service) {
    'all'      { Start-Backend; Start-Frontend }
    'backend'  { Start-Backend }
    'frontend' { Start-Frontend }
}
