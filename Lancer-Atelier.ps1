param([switch]$Restart)

$ErrorActionPreference = 'Stop'
$atelierScript = Join-Path $PSScriptRoot 'run_local.py'
$siteUrl = 'http://127.0.0.1:8765'

if ($Restart) {
    $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if ($process.CommandLine -notlike "*$atelierScript*") {
            throw "Le port 8765 est utilisé par une autre application. Atelier ne l'arrêtera pas."
        }
        Stop-Process -Id $listener.OwningProcess -Force
        Start-Sleep -Milliseconds 500
    }
}

try {
    Invoke-RestMethod "$siteUrl/api/health" -TimeoutSec 2 | Out-Null
} catch {
    Start-Process -FilePath python -ArgumentList @($atelierScript) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
}

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        Invoke-RestMethod "$siteUrl/api/health" -TimeoutSec 1 | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Milliseconds 250
    }
}
if (-not $ready) { throw 'Atelier ne répond pas après le lancement.' }

Start-Process $siteUrl
