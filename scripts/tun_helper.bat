@echo off
setlocal EnableDelayedExpansion

set ACTION=%1
set TUN_DEV=%2
if "%TUN_DEV%"=="" set TUN_DEV=FQoF
set SOCKS_PORT=%3
if "%SOCKS_PORT%"=="" set SOCKS_PORT=10808
set SERVER_IP=%4
if "%SERVER_IP%"=="" set SERVER_IP=127.0.0.1
set SERVER_IP_2=%5
if "%SERVER_IP_2%"=="" set SERVER_IP_2=127.0.0.1

for /f "tokens=3" %%i in ('route print 0.0.0.0 ^| findstr /r "\<0.0.0.0\>"') do (
    if not defined DEF_GW set DEF_GW=%%i
)

if "%ACTION%"=="up" (
    echo [STEALTHPROXY] Setting up Windows TUN routes...

    if defined DEF_GW (
        if not "%SERVER_IP%"=="127.0.0.1" route add %SERVER_IP% mask 255.255.255.255 %DEF_GW% metric 1 >nul 2>&1
        if not "%SERVER_IP_2%"=="127.0.0.1" route add %SERVER_IP_2% mask 255.255.255.255 %DEF_GW% metric 1 >nul 2>&1
    )

    netsh interface ipv4 set address name="%TUN_DEV%" source=static address=198.18.0.1 mask=255.254.0.0 gateway=none >nul 2>&1
    netsh interface ipv4 set subinterface "%TUN_DEV%" mtu=1500 store=active >nul 2>&1

    netsh interface ipv4 set dnsservers name="%TUN_DEV%" static 172.29.172.254 primary validate=no >nul 2>&1

    route add 0.0.0.0 mask 128.0.0.0 198.18.0.1 metric 1 >nul 2>&1
    route add 128.0.0.0 mask 128.0.0.0 198.18.0.1 metric 1 >nul 2>&1

    route add 172.29.172.254 mask 255.255.255.255 198.18.0.1 metric 1 >nul 2>&1

    netsh interface ipv6 set interface "%TUN_DEV%" admin=disable >nul 2>&1

    echo TUN_UP_SUCCESS
    exit /b 0
)

if "%ACTION%"=="down" (
    echo [STEALTHPROXY] Tearing down Windows TUN routes...

    route delete 0.0.0.0 mask 128.0.0.0 >nul 2>&1
    route delete 128.0.0.0 mask 128.0.0.0 >nul 2>&1
    route delete 172.29.172.254 mask 255.255.255.255 >nul 2>&1

    if not "%SERVER_IP%"=="127.0.0.1" route delete %SERVER_IP% mask 255.255.255.255 >nul 2>&1
    if not "%SERVER_IP_2%"=="127.0.0.1" route delete %SERVER_IP_2% mask 255.255.255.255 >nul 2>&1

    echo TUN_DOWN_SUCCESS
    exit /b 0
)

if "%ACTION%"=="status" (
    netsh interface show interface "%TUN_DEV%" >nul 2>&1
    if %errorlevel% equ 0 (
        echo TUN_ACTIVE
    ) else (
        echo TUN_INACTIVE
    )
    exit /b 0
)

echo Usage: %0 {up^|down^|status} [dev] [socks_port] [server_ip1] [server_ip2]
exit /b 1
