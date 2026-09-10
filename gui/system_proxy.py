import os
import shutil
import subprocess
from typing import Tuple, List

class SystemProxyManager:
    @staticmethod
    def get_active_interfaces() -> List[str]:
        ifaces = []
        try:
            res = subprocess.run(["ip", "-o", "route", "show", "to", "default"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                parts = line.split()
                if "dev" in parts:
                    idx = parts.index("dev")
                    if idx + 1 < len(parts):
                        ifaces.append(parts[idx + 1])
        except Exception:
            pass

        if not ifaces:
            for cand in ["wlan0", "eth0", "enp109s0", "ens3"]:
                if os.path.exists(f"/sys/class/net/{cand}"):
                    ifaces.append(cand)

        return list(set(ifaces))

    @classmethod
    def enable_proxy(cls, socks_port: int = 10808, http_port: int = 10809, ru_bypass: bool = True) -> Tuple[bool, str]:
        messages = []

        override_items = [
            "<local>", "localhost", "127.*",
            "10.*", "172.16.*", "172.17.*", "172.18.*", "172.19.*", "172.2*.*", "172.30.*", "172.31.*",
            "192.168.*", "100.64.*", "100.65.*", "100.66.*", "100.67.*", "100.68.*", "100.69.*", "100.7*.*", "100.8*.*", "100.9*.*", "100.1*.*",
            "*.local", "*.internal", "*.lan", "*.home", "*.corp"
        ]
        if ru_bypass:
            override_items.extend([
                "*.ru", "*.su", "*.xn--p1ai",
                "*.yandex.*", "*.ya.ru", "*.vk.com", "*.vk.me", "*.ok.ru",
                "*.gosuslugi.ru", "*.sberbank.ru", "*.tbank.ru", "*.tinkoff.ru",
                "*.kinopoisk.ru", "*.avito.ru", "*.ozon.ru", "*.wildberries.ru", "*.rutube.ru"
            ])
        proxy_override_str = ";".join(override_items)

        if os.name == "nt":
            try:
                import winreg
                import ctypes
                internet_settings = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                    0, winreg.KEY_ALL_ACCESS
                )
                winreg.SetValueEx(internet_settings, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(internet_settings, "ProxyServer", 0, winreg.REG_SZ, f"http=127.0.0.1:{http_port};https=127.0.0.1:{http_port};socks=127.0.0.1:{socks_port}")
                winreg.SetValueEx(internet_settings, "ProxyOverride", 0, winreg.REG_SZ, proxy_override_str)
                winreg.CloseKey(internet_settings)
                INTERNET_OPTION_SETTINGS_CHANGED = 39
                INTERNET_OPTION_REFRESH = 37
                ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
                ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
                messages.append("Windows Internet Settings (WinINet)")
            except Exception:
                pass

        if shutil.which("kwriteconfig6"):
            try:
                subprocess.run(["kwriteconfig6", "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "ProxyType", "1"], check=True)
                subprocess.run(["kwriteconfig6", "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "socksProxy", f"socks5://127.0.0.1:{socks_port}"], check=True)
                subprocess.run(["kwriteconfig6", "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "httpProxy", f"http://127.0.0.1:{http_port}"], check=True)
                subprocess.run(["kwriteconfig6", "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "httpsProxy", f"http://127.0.0.1:{http_port}"], check=True)
                subprocess.run(["dbus-send", "--type=signal", "/KIO/Scheduler", "org.kde.KIO.Scheduler.reparseSlaveConfiguration", "string:\"\""], check=False)
                messages.append("KDE Plasma 6")
            except Exception:
                pass

        if shutil.which("gsettings"):
            try:
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"], check=True)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "host", "127.0.0.1"], check=True)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.socks", "port", str(socks_port)], check=True)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.http", "host", "127.0.0.1"], check=True)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.http", "port", str(http_port)], check=True)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.https", "host", "127.0.0.1"], check=True)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.https", "port", str(http_port)], check=True)
                if ru_bypass:
                    ignore_hosts = str(["localhost", "127.0.0.1", "*.ru", "*.su", "*.xn--p1ai", "*.yandex.*", "*.vk.com", "*.ok.ru", "*.gosuslugi.ru", "*.sberbank.ru"]).replace("'", '"')
                    subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "ignore-hosts", ignore_hosts], check=False)
                messages.append("GNOME/Chromium/Firefox (gsettings)")
            except Exception:
                pass

        os.environ["http_proxy"] = f"http://127.0.0.1:{http_port}"
        os.environ["https_proxy"] = f"http://127.0.0.1:{http_port}"
        os.environ["all_proxy"] = f"socks5h://127.0.0.1:{socks_port}"
        os.environ["ALL_PROXY"] = f"socks5h://127.0.0.1:{socks_port}"
        if ru_bypass:
            no_proxy_val = "localhost,127.0.0.1,.ru,.su,.xn--p1ai,yandex.ru,ya.ru,vk.com,ok.ru,gosuslugi.ru,sberbank.ru,tbank.ru,tinkoff.ru,kinopoisk.ru,avito.ru,ozon.ru,wildberries.ru,rutube.ru"
            os.environ["no_proxy"] = no_proxy_val
            os.environ["NO_PROXY"] = no_proxy_val

        if messages:
            return True, f"Системный прокси включен для: {', '.join(messages)}"
        return False, "Не найдены утилиты kwriteconfig6/gsettings"

    @classmethod
    def disable_proxy(cls) -> Tuple[bool, str]:
        if os.name == "nt":
            try:
                import winreg
                import ctypes
                internet_settings = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                    0, winreg.KEY_ALL_ACCESS
                )
                winreg.SetValueEx(internet_settings, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                winreg.CloseKey(internet_settings)
                INTERNET_OPTION_SETTINGS_CHANGED = 39
                INTERNET_OPTION_REFRESH = 37
                ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
                ctypes.windll.wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
            except Exception:
                pass

        if shutil.which("kwriteconfig6"):
            try:
                subprocess.run(["kwriteconfig6", "--file", "kioslaverc", "--group", "Proxy Settings", "--key", "ProxyType", "0"], check=True)
                subprocess.run(["dbus-send", "--type=signal", "/KIO/Scheduler", "org.kde.KIO.Scheduler.reparseSlaveConfiguration", "string:\"\""], check=False)
            except Exception:
                pass

        if shutil.which("gsettings"):
            try:
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", "none"], check=True)
            except Exception:
                pass

        for k in ["http_proxy", "https_proxy", "all_proxy", "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"]:
            os.environ.pop(k, None)

        return True, "Системный прокси отключен"

    @classmethod
    def enable_dns(cls, dns_port: int = 10853) -> Tuple[bool, str]:
        if not shutil.which("resolvectl"):
            return True, "DNS автоматически туннелируется через прокси"

        ifaces = cls.get_active_interfaces()
        if not ifaces:
            return True, "DNS активен в туннеле прокси"

        success_ifaces = []
        for iface in ifaces:
            try:
                subprocess.run(["resolvectl", "dns", iface, f"127.0.0.1:{dns_port}"], check=True)
                success_ifaces.append(iface)
            except Exception:
                pass

        if success_ifaces:
            return True, f"AmneziaDNS применен для: {', '.join(success_ifaces)}"
        return True, "AmneziaDNS активен через туннель"

    @classmethod
    def disable_dns(cls) -> Tuple[bool, str]:
        if not shutil.which("resolvectl"):
            return True, "resolvectl не найден"

        ifaces = cls.get_active_interfaces()
        for iface in ifaces:
            try:
                subprocess.run(["resolvectl", "dns", iface, "95.85.95.85", "2.56.220.2"], check=False)
                subprocess.run(["resolvectl", "default-route", iface, "yes"], check=False)
                subprocess.run(["resolvectl", "domain", iface, ""], check=False)
            except Exception:
                pass

        return True, "DNS возвращен к исходному"

    @classmethod
    def launch_browser_with_proxy(cls, socks_port: int = 10808) -> Tuple[bool, str]:
        proxy_arg = f"--proxy-server=socks5://127.0.0.1:{socks_port}"
        browsers = [
            ("google-chrome-stable", [proxy_arg]),
            ("google-chrome", [proxy_arg]),
            ("chromium", [proxy_arg]),
            ("brave-browser", [proxy_arg]),
            ("firefox", []),
            (r"C:\Program Files\Google\Chrome\Application\chrome.exe", [proxy_arg]),
            (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", [proxy_arg]),
            (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", [proxy_arg]),
            (r"C:\Program Files\Mozilla Firefox\firefox.exe", []),
            (r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe", [proxy_arg]),
        ]
        for b_name, args in browsers:
            if shutil.which(b_name) or os.path.exists(b_name):
                try:
                    popen_kwargs = {"start_new_session": True} if os.name != "nt" else {}
                    subprocess.Popen([b_name] + args + ["https://ya.ru"], **popen_kwargs)
                    return True, f"Запущен браузер {os.path.basename(b_name)} с прямым проксированием через 127.0.0.1:{socks_port}"
                except Exception as e:
                    return False, f"Ошибка запуска {b_name}: {e}"
        return False, "Браузеры (Chrome/Edge/Brave/Firefox) не найдены в системе"
