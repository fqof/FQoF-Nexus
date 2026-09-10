param (
    [Parameter(Position=0, Mandatory=$true)]
    [string]$Action,

    [Parameter(Position=1)]
    [string]$TunDev = "FQoF",

    [Parameter(Position=2)]
    [int]$SocksPort = 10808,

    [Parameter(Position=3)]
    [string]$ServerIp1 = "127.0.0.1",

    [Parameter(Position=4)]
    [string]$ServerIp2 = "127.0.0.1"
)

$ErrorActionPreference = "SilentlyContinue"

$defRoute = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | 
    Where-Object { 
        $_.InterfaceAlias -notmatch 'FQoF|wintun|Amnezia|WireGuard|OpenVPN|TAP|Tailscale|ZeroTier|wg' -and 
        $_.NextHop -ne '0.0.0.0' -and 
        $_.NextHop -ne 'On-link' 
    } | 
    Sort-Object RouteMetric | 
    Select-Object -First 1

$defGw = if ($defRoute) { $defRoute.NextHop } else { "192.168.1.1" }
$defIfIndex = if ($defRoute) { $defRoute.InterfaceIndex } else { 6 }

$otherVpnActive = [bool](Get-NetAdapter | Where-Object { 
    $_.Name -match 'Amnezia|WireGuard|OpenVPN|TAP|Tailscale|ZeroTier|wg' -and $_.Status -eq 'Up' 
})

$stateFile = Join-Path $env:TEMP "stealthproxy_ipv6_adapters.txt"

if ($Action -eq "up") {
    Write-Host "[STEALTHPROXY] Setting up Windows TUN routes with IPv6 leak protection..."

    $targetIps = @($ServerIp1, $ServerIp2) | Where-Object { $_ -and $_ -ne "127.0.0.1" -and $_ -ne "0.0.0.0" }
    foreach ($ip in $targetIps) {
        $existing = Get-NetRoute -DestinationPrefix "$ip/32" -ErrorAction SilentlyContinue
        if (-not $existing) {
            route add $ip mask 255.255.255.255 $defGw metric 1 IF $defIfIndex | Out-Null
        }
    }

    $tunAdapter = $null
    for ($i = 0; $i -lt 15; $i++) {
        $tunAdapter = Get-NetAdapter -Name $TunDev -ErrorAction SilentlyContinue
        if (-not $tunAdapter) {
            $tunAdapter = Get-NetAdapter | Where-Object { 
                ($_.InterfaceDescription -match '^sing-tun' -or $_.Name -match '^sing-box|^wintun$') -and 
                $_.Name -ne $TunDev -and 
                $_.Name -notmatch 'WireGuard|OpenVPN|TAP|Amnezia|Tailscale|ZeroTier|wg' -and 
                $_.InterfaceDescription -notmatch 'WireGuard|OpenVPN|TAP|Amnezia|Tailscale' 
            } | Select-Object -First 1
            if ($tunAdapter -and $tunAdapter.Name -ne $TunDev) {
                Rename-NetAdapter -InputObject $tunAdapter -NewName $TunDev -ErrorAction SilentlyContinue
                $tunAdapter = Get-NetAdapter -Name $TunDev -ErrorAction SilentlyContinue
            }
        }
        if ($tunAdapter) { break }
        Start-Sleep -Milliseconds 200
    }

    if (-not $tunAdapter) {
        Write-Host "[STEALTHPROXY] TUN adapter $TunDev not ready yet, skipping netsh binding."
        exit 0
    }

    $actualDev = $tunAdapter.Name
    $tunIdx = $tunAdapter.InterfaceIndex

    netsh interface ipv4 set address name="$actualDev" source=static address=198.18.0.1 mask=255.254.0.0 gateway=none | Out-Null
    netsh interface ipv4 set subinterface "$actualDev" mtu=1500 store=active | Out-Null

    netsh interface ipv4 set dnsservers name="$actualDev" static 172.29.172.254 primary validate=no | Out-Null

    route add 0.0.0.0 mask 128.0.0.0 198.18.0.1 metric 1 IF $tunIdx | Out-Null
    route add 128.0.0.0 mask 128.0.0.0 198.18.0.1 metric 1 IF $tunIdx | Out-Null

    route add 172.29.172.254 mask 255.255.255.255 198.18.0.1 metric 1 IF $tunIdx | Out-Null

    if (Test-Path $stateFile) { Remove-Item $stateFile -Force -ErrorAction SilentlyContinue }
    $physAdapters = Get-NetAdapter | Where-Object { $_.Name -notmatch 'FQoF|wintun|Amnezia|WireGuard|OpenVPN|TAP|Tailscale|ZeroTier|wg' -and $_.Status -eq 'Up' }
    foreach ($a in $physAdapters) {
        $binding = Get-NetAdapterBinding -Name $a.Name -ComponentId ms_tcpip6 -ErrorAction SilentlyContinue
        if ($binding -and $binding.Enabled) {
            $a.Name | Out-File -FilePath $stateFile -Append -Encoding utf8
            Disable-NetAdapterBinding -Name $a.Name -ComponentId ms_tcpip6 -ErrorAction SilentlyContinue
        }
    }

    New-NetFirewallRule -Name "StealthProxy-IPv6-Block" -DisplayName "StealthProxy IPv6 Leak Protection" -Direction Outbound -Action Block -RemoteAddress @("2000::/3", "fc00::/7") -ErrorAction SilentlyContinue | Out-Null
    New-NetFirewallRule -Name "StealthProxy-IPv6-DNS" -DisplayName "StealthProxy IPv6 DNS Protection" -Direction Outbound -Action Block -Protocol UDP,TCP -RemotePort 53 -RemoteAddress "fe80::/10" -ErrorAction SilentlyContinue | Out-Null

    netsh interface ipv6 set interface "$TunDev" admin=disable | Out-Null

    $zapretMarker = Join-Path $env:TEMP "stealthproxy_paused_zapret.txt"
    if (Test-Path $zapretMarker) { Remove-Item $zapretMarker -Force -ErrorAction SilentlyContinue }
    $zapretSvc = Get-Service -Name "zapret" -ErrorAction SilentlyContinue
    if ($zapretSvc -and $zapretSvc.Status -eq "Running") {
        Write-Host "[STEALTHPROXY] Pausing conflicting Zapret service to prevent packet corruption in Discord..."
        Stop-Service -Name "zapret" -Force -ErrorAction SilentlyContinue
        "1" | Out-File -FilePath $zapretMarker -Encoding utf8
    }
    Get-Process winws, goodbyedpi -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

    Write-Host "TUN_UP_SUCCESS"
    exit 0
}

if ($Action -eq "down") {
    Write-Host "[STEALTHPROXY] Tearing down Windows TUN routes and restoring IPv6..."

    route delete 0.0.0.0 mask 128.0.0.0 | Out-Null
    route delete 128.0.0.0 mask 128.0.0.0 | Out-Null
    route delete 172.29.172.254 mask 255.255.255.255 | Out-Null

    if (Test-Path $stateFile) {
        $savedAdapters = Get-Content $stateFile -ErrorAction SilentlyContinue
        foreach ($name in $savedAdapters) {
            if ($name -and $name.Trim()) {
                Enable-NetAdapterBinding -Name $name.Trim() -ComponentId ms_tcpip6 -ErrorAction SilentlyContinue
            }
        }
        Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
    }

    Remove-NetFirewallRule -Name "StealthProxy-IPv6-Block" -ErrorAction SilentlyContinue | Out-Null
    Remove-NetFirewallRule -Name "StealthProxy-IPv6-DNS" -ErrorAction SilentlyContinue | Out-Null

    if (-not $otherVpnActive) {
        $targetIps = @($ServerIp1, $ServerIp2) | Where-Object { $_ -and $_ -ne "127.0.0.1" -and $_ -ne "0.0.0.0" }
        foreach ($ip in $targetIps) {
            route delete $ip mask 255.255.255.255 | Out-Null
        }
    } else {
        Write-Host "[STEALTHPROXY] Preserving server endpoint routes because another VPN is active."
    }

    $zapretMarker = Join-Path $env:TEMP "stealthproxy_paused_zapret.txt"
    if (Test-Path $zapretMarker) {
        Write-Host "[STEALTHPROXY] Restoring Zapret service..."
        Start-Service -Name "zapret" -ErrorAction SilentlyContinue
        Remove-Item $zapretMarker -Force -ErrorAction SilentlyContinue
    }

    Write-Host "TUN_DOWN_SUCCESS"
    exit 0
}

if ($Action -eq "status") {
    $tun = Get-NetAdapter -Name $TunDev -ErrorAction SilentlyContinue
    if ($tun -and $tun.Status -eq "Up") {
        Write-Host "TUN_ACTIVE"
    } else {
        Write-Host "TUN_INACTIVE"
    }
    exit 0
}
