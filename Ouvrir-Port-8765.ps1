#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$atelierRule = Get-NetFirewallRule -DisplayName 'Atelier - TCP 8765' -ErrorAction SilentlyContinue
if ($atelierRule) {
    $atelierRule | Enable-NetFirewallRule
} else {
    New-NetFirewallRule -DisplayName 'Atelier - TCP 8765' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Any | Out-Null
}
Write-Host 'Le port TCP 8765 est ouvert pour Atelier.'
