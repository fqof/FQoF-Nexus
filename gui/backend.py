import sys
import atexit
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from PyQt6.QtCore import QObject, pyqtSignal
from gui.secrets import get_secrets

try:
    import psutil
except ImportError:
    psutil = None

class CoreBackend(QObject):
    sig_ready = pyqtSignal()
    sig_started = pyqtSignal(int, int, object, str, bool)
    sig_stopped = pyqtSignal()
    sig_stats = pyqtSignal(dict)
    sig_log = pyqtSignal(str, str)
    sig_error = pyqtSignal(str)
    sig_ping = pyqtSignal(object, object)

    def __init__(self, binary_path: Optional[str] = None):
        super().__init__()
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            self.base_dir = Path(sys._MEIPASS)
        else:
            self.base_dir = Path(__file__).parent.parent
        self.bin_dir = self.base_dir / "bin"

        xray_name = "xray.exe" if os.name == "nt" else "xray"
        tun_name = "tun2socks.exe" if os.name == "nt" else "tun2socks"
        helper_name = "tun_helper.bat" if os.name == "nt" else "tun_helper.sh"
        singbox_name = "sing-box.exe" if os.name == "nt" else "sing-box"

        self.xray_bin = self._find_binary(xray_name)
        self.tun_bin = self._find_binary(tun_name)
        self.singbox_bin = self._find_binary(singbox_name)
        self.helper_script = self._find_helper(helper_name)

        self.xray_process: Optional[subprocess.Popen] = None
        self.tun_process: Optional[subprocess.Popen] = None
        self.active_config_path: Optional[Path] = None
        self.active_tun_config_path: Optional[Path] = None

        self._is_active = False
        self._tun_active = False
        self._tun_type = "none"
        self._tun_full_mode = True
        self._tun_apps: list = []
        self._current_mode = "vless_xhttp"
        self._current_socks_port = 10808
        self._current_http_port = 10809
        self._current_dns_port = 10853
        _srv = get_secrets().get("server", {})
        self._server_ip1 = _srv.get("server_ip1", "127.0.0.1")
        self._server_ip2 = _srv.get("server_ip2", "127.0.0.1")

        self._stats_thread: Optional[threading.Thread] = None
        self._stats_running = False
        self._total_sent = 0
        self._total_recv = 0
        self._last_stats_time = 0.0
        self._last_rx_bytes = 0
        self._last_tx_bytes = 0
        self._ru_subnets_cache: Optional[list] = None

        atexit.register(self.shutdown)

    def _get_ru_bypass_subnets(self) -> list:
        if self._ru_subnets_cache is not None:
            return self._ru_subnets_cache

        candidates = [
            self.base_dir / "ru-bypass.json",
            Path.cwd() / "ru-bypass.json",
            Path(sys._MEIPASS) / "ru-bypass.json" if hasattr(sys, "_MEIPASS") else None,
            Path(sys.executable).parent / "ru-bypass.json",
        ]
        for p in candidates:
            if p and p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    subnets = [d["hostname"].strip() for d in data if d.get("hostname")]
                    if subnets:
                        self._ru_subnets_cache = subnets
                        return self._ru_subnets_cache
                except Exception:
                    pass

        self._ru_subnets_cache = []
        return self._ru_subnets_cache

    def _find_binary(self, name: str) -> Path:
        candidates = [
            self.bin_dir / name,
            self.base_dir / name,
            Path(sys.executable).parent / "bin" / name,
            Path(sys.executable).parent / name,
            Path("C:/Program Files/Xray") / name if os.name == "nt" else Path("/usr/local/bin") / name,
        ]
        for c in candidates:
            if c.exists():
                return c
        which_path = shutil.which(name)
        if which_path:
            return Path(which_path)
        return self.bin_dir / name

    def _find_helper(self, name: str) -> Path:
        candidates = [
            self.bin_dir / name,
            self.base_dir / "scripts" / name,
            self.base_dir / name,
            Path(sys.executable).parent / "bin" / name,
            Path(sys.executable).parent / name,
        ]
        for c in candidates:
            if c.exists():
                return c
        return self.bin_dir / name

    def is_alive(self) -> bool:
        return self._is_active and self.xray_process is not None and self.xray_process.poll() is None

    def start_core(self) -> bool:
        if not self.xray_bin.exists():
            self.sig_error.emit(f"Исполняемый файл Xray не найден: {self.xray_bin}")
            return False

        self.sig_log.emit("info", f"Сетевое ядро готово (Xray: {self.xray_bin.name})")
        self.sig_ready.emit()
        return True

    def _generate_xray_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        socks_port = config.get("socks_port", 10808)
        http_port = config.get("http_port", 10809)
        mode = config.get("mode", "vless_xhttp")
        remote = config.get("remote_proxy", {})
        dns_cfg = config.get("dns", {})
        dns_enabled = dns_cfg.get("enabled", True)
        dns_port = dns_cfg.get("local_port", 10853)
        _srv = get_secrets().get("server", {})
        remote_dns_host = dns_cfg.get("remote_host", _srv.get("remote_dns_host", "1.1.1.1"))
        remote_dns_port = dns_cfg.get("remote_port", _srv.get("remote_dns_port", 53))

        inbounds = [
            {
                "tag": "socks-in",
                "port": socks_port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {
                    "auth": "noauth",
                    "udp": True
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"],
                    "routeOnly": True
                }
            },
            {
                "tag": "http-in",
                "port": http_port,
                "listen": "127.0.0.1",
                "protocol": "http",
                "settings": {
                    "allowTransparent": False
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"],
                    "routeOnly": True
                }
            }
        ]

        effective_dns_host = remote_dns_host if dns_enabled else "1.1.1.1"
        effective_dns_port = remote_dns_port if dns_enabled else 53
        inbounds.append({
            "tag": "dns-in",
            "port": dns_port,
            "listen": "127.0.0.1",
            "protocol": "dokodemo-door",
            "settings": {
                "address": effective_dns_host,
                "port": effective_dns_port,
                "network": "tcp,udp"
            }
        })

        inbounds.append({
            "tag": "api",
            "port": 10085,
            "listen": "127.0.0.1",
            "protocol": "dokodemo-door",
            "settings": {
                "address": "127.0.0.1"
            }
        })

        server_host = remote.get("host", _srv.get("host", "127.0.0.1"))
        server_port = remote.get("port", _srv.get("port", 443))
        uuid = remote.get("uuid", _srv.get("uuid", "00000000-0000-0000-0000-000000000000"))
        skip_cert_verify = remote.get("skip_cert_verify", False)

        outbound_tag = "vless-reality-out" if mode == "vless_reality" else "vless-xhttp-out"

        if mode == "vless_reality":
            sni = remote.get("sni") or _srv.get("reality_sni", "api.weatherapi.com")
            pub_key = remote.get("reality_public_key") or _srv.get("reality_public_key", "")
            short_id = remote.get("reality_short_id") or _srv.get("reality_short_id", "")
            outbound = {
                "tag": outbound_tag,
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": server_host,
                            "port": server_port,
                            "users": [
                                {
                                    "id": uuid,
                                    "flow": "xtls-rprx-vision",
                                    "encryption": "none"
                                }
                            ]
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "packetEncoding": "xudp",
                    "realitySettings": {
                        "show": False,
                        "fingerprint": "chrome",
                        "serverName": sni,
                        "publicKey": pub_key,
                        "shortId": short_id,
                        "spiderX": "/"
                    }
                }
            }
        else:
            sni = remote.get("sni") or _srv.get("sni", "example.com")
            xhttp_path = remote.get("path") or _srv.get("path", "/api/v1/telemetry")
            pq_enc = remote.get("post_quantum_encryption") or _srv.get("post_quantum_encryption", "")

            outbound = {
                "tag": outbound_tag,
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": server_host,
                            "port": server_port,
                            "users": [
                                {
                                    "id": uuid,
                                    "encryption": pq_enc
                                }
                            ]
                        }
                    ]
                },
                "streamSettings": {
                    "network": "xhttp",
                    "security": "tls",
                    "packetEncoding": "xudp",
                    "tlsSettings": {
                        "serverName": sni,
                        "fingerprint": "chrome",
                        "alpn": ["h2", "http/1.1"],
                        "allowInsecure": skip_cert_verify
                    },
                    "xhttpSettings": {
                        "path": xhttp_path,
                        "mode": "stream-one",
                        "xPaddingBytes": "100-500",
                        "xmux": {
                            "maxConcurrency": 256,
                            "cMaxReuseTimes": 256,
                            "hMaxRequestTimes": 500
                        },
                        "headers": {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                        }
                    }
                }
            }

        dpi_cfg = config.get("dpi", {})
        dpi_enabled = dpi_cfg.get("enabled", False)

        outbounds = [outbound]

        if dpi_enabled:
            stream_settings = outbound.setdefault("streamSettings", {})
            sockopt = stream_settings.setdefault("sockopt", {})
            sockopt["dialerProxy"] = "fragment-out"

            fragment_outbound = {
                "tag": "fragment-out",
                "protocol": "freedom",
                "settings": {
                    "domainStrategy": "UseIPv4",
                    "fragment": {
                        "packets": dpi_cfg.get("packets", "tlshello"),
                        "length": dpi_cfg.get("length", "1-3"),
                        "interval": dpi_cfg.get("interval", "1-2")
                    }
                }
            }
            outbounds.append(fragment_outbound)

        outbounds.append({
            "tag": "direct",
            "protocol": "freedom",
            "settings": {
                "domainStrategy": "UseIPv4"
            }
        })

        outbounds.append({
            "tag": "block-ipv6",
            "protocol": "blackhole",
            "settings": {
                "response": {"type": "none"}
            }
        })

        ru_bypass_enabled = config.get("ru_bypass", True)
        routing_rules = [
            {
                "type": "field",
                "inboundTag": ["api"],
                "outboundTag": "api"
            },
            {
                "type": "field",
                "ip": ["::/0"],
                "outboundTag": "block-ipv6"
            },
            {
                "type": "field",
                "inboundTag": ["dns-in"],
                "outboundTag": outbound_tag
            },
            {
                "type": "field",
                "ip": [
                    "geoip:private",
                    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                    "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "224.0.0.0/4"
                ],
                "outboundTag": "direct"
            },
            {
                "type": "field",
                "domain": ["domain:local", "domain:internal", "domain:lan", "domain:home", "domain:corp", "domain:onion"],
                "outboundTag": "direct"
            }
        ]

        ru_domains = [
            "domain:ru", "domain:su", "domain:xn--p1ai",
            "yandex.ru", "yandex.net", "ya.ru", "vk.com", "vk.me", "ok.ru",
            "gosuslugi.ru", "sberbank.ru", "tbank.ru", "tinkoff.ru",
            "kinopoisk.ru", "avito.ru", "ozon.ru", "wildberries.ru", "rutube.ru"
        ]

        if ru_bypass_enabled:
            ru_subnets = self._get_ru_bypass_subnets()
            if ru_subnets:
                routing_rules.append({
                    "type": "field",
                    "ip": ru_subnets,
                    "outboundTag": "direct"
                })
            routing_rules.append({
                "type": "field",
                "domain": ru_domains,
                "outboundTag": "direct"
            })
        else:
            routing_rules.append({
                "type": "field",
                "inboundTag": ["socks-in", "http-in"],
                "outboundTag": outbound_tag
            })

        dns_servers = [
            remote_dns_host if dns_enabled else "1.1.1.1",
            "1.1.1.1",
            "8.8.8.8"
        ]
        if ru_bypass_enabled:
            dns_servers.insert(0, {
                "address": "77.88.8.8",
                "port": 53,
                "domains": ru_domains
            })

        return {
            "log": {
                "loglevel": "warning"
            },
            "stats": {},
            "api": {
                "tag": "api",
                "services": ["StatsService"]
            },
            "policy": {
                "levels": {
                    "0": {
                        "statsUserUplink": True,
                        "statsUserDownlink": True
                    }
                },
                "system": {
                    "statsInboundUplink": True,
                    "statsInboundDownlink": True,
                    "statsOutboundUplink": True,
                    "statsOutboundDownlink": True
                }
            },
            "dns": {
                "servers": dns_servers,
                "queryStrategy": "UseIPv4"
            },
            "routing": {
                "domainStrategy": "IPIfNonMatch" if ru_bypass_enabled else "UseIPv4",
                "rules": routing_rules
            },
            "inbounds": inbounds,
            "outbounds": outbounds
        }

    def _wait_for_port(self, port: int, timeout: float = 3.5) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    return True
            except OSError:
                time.sleep(0.05)
        return False

    def start_proxy(self, config: Dict[str, Any]):
        threading.Thread(target=self._do_start_proxy, args=(config,), daemon=True).start()

    def _do_start_proxy(self, config: Dict[str, Any]):
        self.stop_proxy(notify=False)

        if not self.xray_bin.exists():
            self.sig_error.emit(f"Бинарный файл Xray не найден: {self.xray_bin}")
            return

        try:
            xray_cfg = self._generate_xray_config(config)
            cfg_file = Path(tempfile.gettempdir()) / "xray_nexus_config.json"
            cfg_file.write_text(json.dumps(xray_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            self.active_config_path = cfg_file

            mode = config.get("mode", "vless_xhttp")
            socks_port = config.get("socks_port", 10808)
            http_port = config.get("http_port", 10809)
            dns_port = config.get("dns", {}).get("local_port", 10853) if config.get("dns", {}).get("enabled") else None
            remote = config.get("remote_proxy", {})
            _srv = get_secrets().get("server", {})
            self._server_ip1 = remote.get("host", _srv.get("server_ip1", "127.0.0.1"))
            self._server_ip2 = _srv.get("server_ip2", "127.0.0.1")

            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self.xray_process = subprocess.Popen(
                [str(self.xray_bin), "run", "-config", str(cfg_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **kwargs
            )

            if not self._wait_for_port(socks_port, timeout=3.5):
                err = ""
                if self.xray_process and self.xray_process.stderr:
                    try:
                        err = self.xray_process.stderr.read()
                    except Exception:
                        pass
                self.sig_error.emit(f"Xray не смог открыть порты прокси: {err.strip()[:300]}")
                self.stop_proxy()
                return

            self._is_active = True
            self._current_mode = mode
            self._current_socks_port = socks_port
            self._current_http_port = http_port
            self._current_dns_port = dns_port or 10853

            if mode == "vless_reality":
                self.sig_log.emit("info", f"VLESS + REALITY (FakeTLS) запущен: маскировка под {remote.get('sni', _srv.get('reality_sni', 'api.weatherapi.com'))}")
            else:
                self.sig_log.emit("info", f"VLESS + XHTTP [ML-KEM-768] туннель запущен к {self._server_ip1}:{remote.get('port', 443)}")

            dpi_active = config.get("dpi", {}).get("enabled", False)
            if dpi_active:
                f_len = config.get("dpi", {}).get("length", "1-3")
                f_int = config.get("dpi", {}).get("interval", "1-2")
                self.sig_log.emit("info", f"🛡️ Обход ТСПУ: TLS ClientHello фрагментация [{f_len} байт, задержка {f_int} мс]")
            if mode == "vless_xhttp":
                self.sig_log.emit("info", "🕶️ XHTTP Ghost: рандомизация Padding (100-500B) и ротация xmux сокетов активны")

            tun_cfg = config.get("tun", {})
            tun_cfg["ru_bypass"] = config.get("ru_bypass", True)
            is_tun = tun_cfg.get("enabled", False)
            if is_tun:
                self._activate_tun(socks_port, tun_cfg)

            if config.get("ru_bypass", True):
                self.sig_log.emit("info", "🇷🇺 Прямой доступ для сайтов РФ (ru-bypass): 8 700+ подсетей и домены .ru/.рф идут напрямую")

            self.sig_started.emit(socks_port, http_port, dns_port, mode, self._tun_active)
            self._start_stats_loop()

        except Exception as e:
            self.sig_error.emit(f"Ошибка запуска прокси: {e}")
            self.stop_proxy()

    def _activate_tun(self, socks_port: int, tun_config: Optional[dict] = None):
        tun_cfg = tun_config or {}
        full_mode = tun_cfg.get("full_mode", True)
        ru_bypass = tun_cfg.get("ru_bypass", True)
        raw_apps = tun_cfg.get("apps", [])
        apps = [a.lower().strip() for a in raw_apps if a and a.strip()]
        self._tun_full_mode = full_mode
        self._tun_apps = apps

        if os.name == "nt":
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():
                self.sig_log.emit("warn", "⚠️ Режим TUN требует запуска от имени Администратора для настройки сетевого адаптера!")

        if self.singbox_bin.exists():
            self._activate_singbox_tun(socks_port, full_mode, apps, ru_bypass=ru_bypass)
            return

        if self.tun_bin.exists():
            if not full_mode:
                self.sig_log.emit("warn", "⚠️ Для раздельного TUN (по приложениям) рекомендуется sing-box. Запуск общего tun2socks...")
            self._activate_tun2socks(socks_port)
            return

        self.sig_log.emit("warn", f"Бинарные файлы TUN не найдены. Трафик доступен через прокси 127.0.0.1:{socks_port}")

    def _activate_singbox_tun(self, socks_port: int, full_mode: bool, apps: list, ru_bypass: bool = True):
        dev_name = "FQoF" if os.name == "nt" else "tun0"
        dns_port = self._current_dns_port or 10853

        expanded_apps = set()
        for a in apps:
            base = a.lower().replace(".exe", "").strip()
            if not base:
                continue
            expanded_apps.update([
                f"{base}.exe",
                f"{base.capitalize()}.exe",
                f"{base.upper()}.exe",
                base,
                base.capitalize()
            ])
            if "discord" in base:
                expanded_apps.update(["Discord.exe", "discord.exe", "DISCORD.EXE", "DiscordCanary.exe", "DiscordPTB.exe"])
            elif "telegram" in base:
                expanded_apps.update(["Telegram.exe", "telegram.exe", "TELEGRAM.EXE"])
            elif "steam" in base:
                expanded_apps.update(["steam.exe", "Steam.exe", "STEAM.EXE", "steamwebhelper.exe", "SteamWebHelper.exe", "steamservice.exe", "SteamService.exe"])
            elif "cs2" in base or "csgo" in base:
                expanded_apps.update(["cs2.exe", "CS2.exe", "csgo.exe", "CSGO.exe"])

        proc_list = sorted(list(expanded_apps))

        dns_servers = [
            {
                "tag": "dns-remote",
                "type": "udp",
                "server": "127.0.0.1",
                "server_port": dns_port
            },
            {
                "tag": "dns-direct",
                "type": "local"
            }
        ]

        outbounds = [
            {
                "type": "socks",
                "tag": "socks-out",
                "server": "127.0.0.1",
                "server_port": socks_port
            },
            {
                "type": "direct",
                "tag": "direct"
            }
        ]

        ru_domains = [
            "ru", "su", "xn--p1ai",
            "yandex.ru", "yandex.net", "ya.ru", "vk.com", "vk.me", "ok.ru",
            "gosuslugi.ru", "sberbank.ru", "tbank.ru", "tinkoff.ru",
            "kinopoisk.ru", "avito.ru", "ozon.ru", "wildberries.ru", "rutube.ru"
        ]
        ru_subnets = self._get_ru_bypass_subnets() if ru_bypass else []

        vpn_bypass_processes = [
            "wireguard.exe", "wireguard", "wireguard-service.exe", "wg.exe",
            "openvpn.exe", "openvpn", "openvpnserv.exe", "openvpnserv2.exe", "openvpn-gui.exe",
            "tapinstall.exe", "xray.exe", "xray", "sing-box.exe", "sing-box"
        ]
        local_domains = [
            "local", "internal", "lan", "home", "corp", "corp.local", "onion", "arpa"
        ]
        private_cidrs = [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "100.64.0.0/10",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "224.0.0.0/4"
        ]

        if full_mode:
            dns_rules = [
                {"domain_suffix": local_domains, "server": "dns-direct"},
                {"process_name": vpn_bypass_processes, "server": "dns-direct"}
            ]
            if ru_bypass:
                dns_rules.append({
                    "domain_suffix": ru_domains,
                    "server": "dns-direct"
                })
            dns_final = "dns-remote"
            route_rules = [
                {"protocol": "dns", "action": "hijack-dns"},
                {"action": "sniff"},
                {"process_name": vpn_bypass_processes, "outbound": "direct"},
                {"ip_cidr": private_cidrs, "outbound": "direct"}
            ]
            if ru_bypass:
                if ru_subnets:
                    route_rules.append({"ip_cidr": ru_subnets, "outbound": "direct"})
                route_rules.append({"domain_suffix": ru_domains, "outbound": "direct"})
            route_rules.append({"outbound": "socks-out"})
        else:
            dns_rules = [
                {"domain_suffix": local_domains, "server": "dns-direct"},
                {"process_name": vpn_bypass_processes, "server": "dns-direct"},
                {
                    "domain_suffix": [
                        "telegram.org", "t.me", "telegra.ph", "telegram.me", "telesco.pe",
                        "discord.com", "discord.gg", "discordapp.com", "discordapp.net", "discordstatus.com",
                        "steamcommunity.com", "steampowered.com", "steamstatic.com", "steamgames.com"
                    ],
                    "server": "dns-remote"
                }
            ]
            if ru_bypass:
                dns_rules.append({
                    "domain_suffix": ru_domains,
                    "server": "dns-direct"
                })
            if proc_list:
                dns_rules.append({"process_name": proc_list, "server": "dns-remote"})
            dns_final = "dns-direct"
            route_rules = [
                {"protocol": "dns", "action": "hijack-dns"},
                {"action": "sniff"},
                {"process_name": vpn_bypass_processes, "outbound": "direct"},
                {"ip_cidr": private_cidrs, "outbound": "direct"}
            ]
            if ru_bypass:
                if ru_subnets:
                    route_rules.append({"ip_cidr": ru_subnets, "outbound": "direct"})
                route_rules.append({"domain_suffix": ru_domains, "outbound": "direct"})
            if proc_list:
                route_rules.append({"process_name": proc_list, "outbound": "socks-out"})
            route_rules.append({"outbound": "direct"})

        sb_config = {
            "log": {
                "level": "warn"
            },
            "dns": {
                "servers": dns_servers,
                "rules": dns_rules,
                "final": dns_final,
                "strategy": "ipv4_only"
            },
            "inbounds": [
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "interface_name": dev_name,
                    "address": ["172.19.0.1/30"],
                    "auto_route": True,
                    "strict_route": False,
                    "route_exclude_address": [
                        "10.0.0.0/8",
                        "172.16.0.0/12",
                        "192.168.0.0/16",
                        "100.64.0.0/10"
                    ],
                    "stack": "mixed"
                }
            ],
            "outbounds": outbounds,
            "route": {
                "find_process": True,
                "auto_detect_interface": True,
                "default_domain_resolver": "dns-direct",
                "rules": route_rules
            }
        }

        cfg_file = Path(tempfile.gettempdir()) / "singbox_nexus_tun.json"
        cfg_file.write_text(json.dumps(sb_config, indent=2, ensure_ascii=False), encoding="utf-8")
        self.active_tun_config_path = cfg_file

        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            self.tun_process = subprocess.Popen(
                [str(self.singbox_bin), "run", "-c", str(cfg_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **kwargs
            )
            time.sleep(0.6)
            if self.tun_process.poll() is not None:
                err = ""
                if self.tun_process.stderr:
                    try:
                        err = self.tun_process.stderr.read().decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                if dev_name != "wintun" and os.name == "nt":
                    sb_config["inbounds"][0]["interface_name"] = "wintun"
                    cfg_file.write_text(json.dumps(sb_config, indent=2, ensure_ascii=False), encoding="utf-8")
                    self.tun_process = subprocess.Popen(
                        [str(self.singbox_bin), "run", "-c", str(cfg_file)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        **kwargs
                    )
                    time.sleep(0.6)

                if self.tun_process.poll() is not None:
                    err = ""
                    if self.tun_process.stderr:
                        try:
                            err = self.tun_process.stderr.read().decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                    self.sig_log.emit("warn", f"sing-box завершился с ошибкой: {err.strip()[:200]}")
                    self._tun_active = False
                    return

            self._tun_active = True
            self._tun_type = "singbox"

            if os.name == "nt":
                threading.Thread(target=self._try_rename_adapter_to_fqof, daemon=True).start()

            if full_mode:
                self.sig_log.emit("info", "🛡️ TUN адаптер (FQoF) успешно активирован: 100% трафика системы защищено через VPN")
            else:
                apps_str = ", ".join(apps) if apps else "нет"
                self.sig_log.emit("info", f"🎯 Изолированный TUN активен для: [{apps_str}] (весь остальной трафик Windows идёт напрямую)")
        except Exception as e:
            self.sig_log.emit("warn", f"Не удалось запустить sing-box TUN: {e}")
            self._tun_active = False

    def _try_rename_adapter_to_fqof(self):
        if os.name != "nt":
            return
        time.sleep(1.0)
        try:
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   "$a = Get-NetAdapter | Where-Object { ($_.InterfaceDescription -match '^sing-tun' -or $_.Name -match '^sing-box|^wintun$') -and $_.Name -ne 'FQoF' -and $_.Name -notmatch 'WireGuard|OpenVPN|TAP|Amnezia|Tailscale|ZeroTier|wg' -and $_.InterfaceDescription -notmatch 'WireGuard|OpenVPN|TAP|Amnezia|Tailscale' } | Select-Object -First 1; if ($a) { Rename-NetAdapter -InputObject $a -NewName 'FQoF' -ErrorAction SilentlyContinue }"]
            subprocess.run(cmd, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
        except Exception:
            pass

    def _activate_tun2socks(self, socks_port: int):
        dev_name = "FQoF" if os.name == "nt" else "tun0"
        proxy_url = f"socks5://127.0.0.1:{socks_port}"

        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            tun_args = [
                str(self.tun_bin),
                "--device", dev_name,
                "--proxy", proxy_url,
                "--mtu", "1500",
                "--tcp-auto-tuning",
                "--udp-timeout", "60s",
                "--loglevel", "warning"
            ]
            self.tun_process = subprocess.Popen(
                tun_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **kwargs
            )
            time.sleep(0.6)

            if self.helper_script.exists():
                if os.name == "nt":
                    cmd = ["cmd.exe", "/c", str(self.helper_script), "up", dev_name, str(socks_port), self._server_ip1, self._server_ip2]
                else:
                    cmd = ["sudo", str(self.helper_script), "up", dev_name, str(socks_port), self._server_ip1, self._server_ip2]

                subprocess.run(cmd, capture_output=True, timeout=8, **kwargs)

            self._tun_active = True
            self._tun_type = "tun2socks"
            self.sig_log.emit("info", f"🛡️ TUN адаптер {dev_name} успешно активирован (tun2socks): 100% трафика ОС защищено")
        except Exception as e:
            self.sig_log.emit("warn", f"Не удалось поднять TUN режим: {e}")
            self._tun_active = False

    def update_tun_apps(self, apps: list, full_mode: bool = False):
        """Dynamically update TUN apps while proxy is active."""
        if not self._is_active:
            return

        apps_clean = [a.lower().strip() for a in apps if a and a.strip()]
        self._tun_apps = apps_clean
        self._tun_full_mode = full_mode
        need_tun = full_mode or len(apps_clean) > 0

        if self._tun_active and self.tun_process:
            if not need_tun:
                self._stop_tun_process()
                self._tun_active = False
                self.sig_log.emit("info", "🎯 Фоновый TUN отключен (список приложений пуст)")
                return
            self._stop_tun_process()
            self._activate_tun(self._current_socks_port, {"full_mode": full_mode, "apps": apps_clean})
        elif need_tun:
            self._activate_tun(self._current_socks_port, {"full_mode": full_mode, "apps": apps_clean})

    def _stop_tun_process(self):
        if self.tun_process:
            try:
                self.tun_process.terminate()
                self.tun_process.wait(timeout=1.5)
            except Exception:
                try:
                    self.tun_process.kill()
                except Exception:
                    pass
            self.tun_process = None

        if self._tun_type == "tun2socks" and self.helper_script.exists():
            dev_name = "FQoF" if os.name == "nt" else "tun0"
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            try:
                if os.name == "nt":
                    cmd = ["cmd.exe", "/c", str(self.helper_script), "down", dev_name, str(self._current_socks_port), self._server_ip1, self._server_ip2]
                else:
                    cmd = ["sudo", str(self.helper_script), "down", dev_name, str(self._current_socks_port), self._server_ip1, self._server_ip2]
                subprocess.run(cmd, capture_output=True, timeout=5, **kwargs)
            except Exception:
                pass

        self._tun_type = "none"
        if self.active_tun_config_path and self.active_tun_config_path.exists():
            try:
                self.active_tun_config_path.unlink()
            except Exception:
                pass

    def stop_proxy(self, notify: bool = True):
        was_running = self._is_active or self._tun_active or (self.xray_process is not None)
        self._stats_running = False
        self._is_active = False

        self._stop_tun_process()
        self._tun_active = False

        if self.xray_process:
            try:
                self.xray_process.terminate()
                self.xray_process.wait(timeout=1.0)
            except Exception:
                try:
                    self.xray_process.kill()
                except Exception:
                    pass
            self.xray_process = None

        if self.active_config_path and self.active_config_path.exists():
            try:
                self.active_config_path.unlink()
            except Exception:
                pass

        if notify and was_running:
            self.sig_stopped.emit()

    def _query_xray_stats(self) -> Tuple[int, int]:
        if not self.xray_bin or not self.xray_bin.exists():
            return 0, 0
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            cmd = [str(self.xray_bin), "api", "statsquery", "--server=127.0.0.1:10085"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=0.6, creationflags=flags)
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                rx = 0
                tx = 0
                for item in data.get("stat", []):
                    name = item.get("name", "")
                    val = item.get("value", 0)
                    if "api" in name:
                        continue
                    if "inbound" in name:
                        if "downlink" in name:
                            rx += val
                        elif "uplink" in name:
                            tx += val
                return rx, tx
        except Exception:
            pass
        return 0, 0

    def _query_tun_adapter_stats(self) -> Tuple[int, int]:
        if not psutil:
            return 0, 0
        try:
            counters = psutil.net_io_counters(pernic=True)
            for iface, c in counters.items():
                if any(k in iface.lower() for k in ["fqof", "wintun", "sing-tun", "tun0"]):
                    return c.bytes_recv, c.bytes_sent
        except Exception:
            pass
        return 0, 0

    def _start_stats_loop(self):
        self._stats_running = True
        self._last_stats_time = time.time()
        self._last_xray_rx = 0
        self._last_xray_tx = 0
        self._last_tun_rx = 0
        self._last_tun_tx = 0

        def loop():
            while self._stats_running and self._is_active:
                time.sleep(1.0)
                now = time.time()
                dt = max(0.1, now - self._last_stats_time)
                self._last_stats_time = now

                upload_speed = 0
                download_speed = 0

                xray_rx, xray_tx = self._query_xray_stats()
                xray_rx_delta = 0
                xray_tx_delta = 0
                if self._last_xray_rx > 0 or self._last_xray_tx > 0:
                    xray_rx_delta = max(0, xray_rx - self._last_xray_rx)
                    xray_tx_delta = max(0, xray_tx - self._last_xray_tx)
                if xray_rx > 0 or xray_tx > 0 or self._last_xray_rx > 0:
                    self._last_xray_rx = xray_rx
                    self._last_xray_tx = xray_tx

                tun_rx_delta = 0
                tun_tx_delta = 0
                if self._tun_active:
                    tun_rx, tun_tx = self._query_tun_adapter_stats()
                    if self._last_tun_rx > 0 or self._last_tun_tx > 0:
                        tun_rx_delta = max(0, tun_rx - self._last_tun_rx)
                        tun_tx_delta = max(0, tun_tx - self._last_tun_tx)
                    if tun_rx > 0 or tun_tx > 0:
                        self._last_tun_rx = tun_rx
                        self._last_tun_tx = tun_tx

                if self._tun_active and (tun_rx_delta > 0 or tun_tx_delta > 0):
                    rx_delta = tun_rx_delta
                    tx_delta = tun_tx_delta
                else:
                    rx_delta = xray_rx_delta
                    tx_delta = xray_tx_delta

                download_speed = int(rx_delta / dt)
                upload_speed = int(tx_delta / dt)
                self._total_recv += rx_delta
                self._total_sent += tx_delta

                snapshot = {
                    "upload_speed": upload_speed,
                    "download_speed": download_speed,
                    "upload_rate": upload_speed,
                    "download_rate": download_speed,
                    "total_uploaded": self._total_sent,
                    "total_downloaded": self._total_recv,
                }
                self.sig_stats.emit(snapshot)

        self._stats_thread = threading.Thread(target=loop, daemon=True)
        self._stats_thread.start()

    def test_ping(self, host: str, port: int):
        def worker():
            t0 = time.time()
            try:
                with socket.create_connection((host, port), timeout=3.0):
                    latency = int((time.time() - t0) * 1000)
                    self.sig_ping.emit(latency, None)
            except Exception as e:
                self.sig_ping.emit(None, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def shutdown(self):
        self.stop_proxy()
