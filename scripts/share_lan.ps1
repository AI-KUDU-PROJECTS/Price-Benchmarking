param(
    [Parameter(Mandatory = $true)][string]$WslIp,
    [int]$Port = 5173
)

$ErrorActionPreference = "Stop"
$ruleName = "Kudu Price Intelligence $Port"

function Get-PortProxyTarget {
    $lines = netsh interface portproxy show v4tov4 2>$null
    if (-not $lines) { return $null }
    foreach ($line in $lines) {
        if ($line -match "^\s*0\.0\.0\.0\s+$Port\s+(\S+)\s+$Port\s*$") {
            return $Matches[1]
        }
    }
    return $null
}

function Get-ShareIp {
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "172.27.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Sort-Object {
            if ($_.IPAddress -like "192.168.*") { 0 }
            elseif ($_.IPAddress -like "10.*") { 1 }
            else { 2 }
        }
    if ($candidates) { return $candidates[0].IPAddress }
    return $null
}

function Test-FirewallRule {
    return [bool](Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)
}

$currentTarget = Get-PortProxyTarget
$firewallReady = Test-FirewallRule
if ($currentTarget -eq $WslIp -and $firewallReady) {
    $shareIp = Get-ShareIp
    if ($shareIp) { Write-Output "SHARE_URL=http://${shareIp}:${Port}" }
    Write-Output "SHARE_STATUS=already-configured"
    exit 0
}

$script = @"
`$wsl = '$WslIp'
`$port = $Port
`$ruleName = '$ruleName'
netsh interface portproxy delete v4tov4 listenport=`$port listenaddress=0.0.0.0 | Out-Null
netsh interface portproxy add v4tov4 listenport=`$port listenaddress=0.0.0.0 connectport=`$port connectaddress=`$wsl | Out-Null
if (-not (Get-NetFirewallRule -DisplayName `$ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName `$ruleName -Direction Inbound -Protocol TCP -LocalPort `$port -Action Allow | Out-Null
}
"@

$tmp = Join-Path $env:TEMP "kudu-share-$Port.ps1"
Set-Content -Path $tmp -Value $script -Encoding UTF8
Start-Process powershell -Verb RunAs -Wait -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $tmp
) | Out-Null

$shareIp = Get-ShareIp
if ($shareIp) { Write-Output "SHARE_URL=http://${shareIp}:${Port}" }

if ((Get-PortProxyTarget) -eq $WslIp) {
    Write-Output "SHARE_STATUS=updated"
    exit 0
}

Write-Output "SHARE_STATUS=needs-admin"
exit 1
