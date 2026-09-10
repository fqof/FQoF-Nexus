"""
FQoF Nexus Profile Daemon
Manages dynamic per-device VLESS profiles stored in SQLite at /wtf/vpn/vpn_profiles.db
and automatically synchronizes clients with Xray config at /usr/local/etc/xray/config.json.
"""

import json
import logging
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = "/wtf/vpn/vpn_profiles.db"
XRAY_CONFIG_PATH = "/usr/local/etc/xray/config.json"
XRAY_BIN_PATH = "/usr/local/bin/xray"
SERVER_PORT = 28899
SERVER_HOST = "127.0.0.1"

def _load_daemon_secrets():
    from pathlib import Path
    import json
    for p in [Path("secrets.json"), Path("../secrets.json"), Path("/wtf/vpn/secrets.json")]:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as sf:
                    return json.load(sf)
            except Exception:
                pass
    return {}

_DAEMON_SECRETS = _load_daemon_secrets()
_SRV = _DAEMON_SECRETS.get("server", {})
DEFAULT_UUID = _SRV.get("uuid", "00000000-0000-0000-0000-000000000000")
REALITY_PUBLIC_KEY = _SRV.get("reality_public_key", "")
REALITY_SHORT_ID = _SRV.get("reality_short_id", "")
PQ_ENCRYPTION_KEY = _SRV.get("post_quantum_encryption", "")
DEFAULT_HOST = _SRV.get("host", "127.0.0.1")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/wtf/vpn/nexus_server.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

db_lock = threading.Lock()
xray_lock = threading.Lock()

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vpn_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hwid TEXT UNIQUE NOT NULL,
                    uuid TEXT UNIQUE NOT NULL,
                    client_name TEXT DEFAULT '',
                    os_info TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    last_ip TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vpn_profiles_hwid ON vpn_profiles(hwid)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vpn_profiles_uuid ON vpn_profiles(uuid)")
            conn.commit()
    logging.info("SQLite database initialized at %s", DB_PATH)

def load_all_active_uuids() -> set:
    with db_lock:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT uuid FROM vpn_profiles WHERE is_active = 1")
            uuids = {row["uuid"] for row in cursor.fetchall()}
    uuids.add(DEFAULT_UUID)
    return uuids

def sync_xray_config() -> bool:
    """
    Ensures all active UUIDs from database exist in /usr/local/etc/xray/config.json.
    Restarts xray if changes were made.
    """
    with xray_lock:
        try:
            if not os.path.exists(XRAY_CONFIG_PATH):
                logging.error("Xray config not found at %s", XRAY_CONFIG_PATH)
                return False

            active_uuids = load_all_active_uuids()

            with open(XRAY_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)

            changed = False
            inbounds = config.get("inbounds", [])

            for inbound in inbounds:
                tag = inbound.get("tag", "")
                protocol = inbound.get("protocol", "")
                if protocol != "vless":
                    continue

                settings = inbound.setdefault("settings", {})
                clients = settings.setdefault("clients", [])
                old_client_count = len(clients)
                clients = [c for c in clients if isinstance(c, dict) and c.get("id") in active_uuids]
                if len(clients) != old_client_count:
                    changed = True

                existing_ids = {c.get("id") for c in clients if isinstance(c, dict)}
                settings["clients"] = clients

                is_reality = "reality" in tag or inbound.get("streamSettings", {}).get("security") == "reality"

                for u in active_uuids:
                    if u not in existing_ids:
                        changed = True
                        if is_reality:
                            clients.append({
                                "id": u,
                                "flow": "xtls-rprx-vision"
                            })
                        else:
                            clients.append({
                                "id": u,
                                "level": 0
                            })
                        existing_ids.add(u)

            if not changed:
                logging.info("Xray config already up to date with %d UUIDs", len(active_uuids))
                return True

            tmp_path = "/usr/local/etc/xray/config.tmp.json"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            test_res = subprocess.run(
                [XRAY_BIN_PATH, "run", "-test", "-format", "json", "-config", tmp_path],
                capture_output=True,
                text=True
            )
            if test_res.returncode != 0:
                logging.error("Xray config test failed (code %d):\nSTDOUT: %s\nSTDERR: %s",
                              test_res.returncode, test_res.stdout, test_res.stderr)
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                return False

            os.replace(tmp_path, XRAY_CONFIG_PATH)
            logging.info("Xray config updated. Restarting xray service...")

            restart_res = subprocess.run(
                ["systemctl", "restart", "xray"],
                capture_output=True,
                text=True
            )
            if restart_res.returncode != 0:
                logging.error("systemctl restart xray failed: %s", restart_res.stderr)
                return False

            logging.info("Xray restarted successfully with updated clients.")
            return True

        except Exception as e:
            logging.exception("Failed to sync Xray config: %s", e)
            return False

def get_or_register_profile(hwid: str, client_name: str = "", os_info: str = "", client_ip: str = "") -> dict:
    import uuid as uuid_module
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_hwid = hwid.strip().lower()

    with db_lock:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT uuid, client_name, os_info, is_active FROM vpn_profiles WHERE hwid = ?",
                (clean_hwid,)
            )
            row = cursor.fetchone()

            if row:
                profile_uuid = row["uuid"]
                is_active = row["is_active"]
                conn.execute("""
                    UPDATE vpn_profiles
                    SET last_seen = ?,
                        last_ip = ?,
                        client_name = CASE WHEN ? != '' THEN ? ELSE client_name END,
                        os_info = CASE WHEN ? != '' THEN ? ELSE os_info END
                    WHERE hwid = ?
                """, (now_iso, client_ip, client_name, client_name, os_info, os_info, clean_hwid))
                conn.commit()
                is_new = False
            else:
                profile_uuid = str(uuid_module.uuid4())
                conn.execute("""
                    INSERT INTO vpn_profiles (hwid, uuid, client_name, os_info, created_at, last_seen, last_ip, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (clean_hwid, profile_uuid, client_name, os_info, now_iso, now_iso, client_ip))
                conn.commit()
                is_new = True

    sync_xray_config()

    return {
        "status": "success",
        "hwid": clean_hwid,
        "uuid": profile_uuid,
        "is_new": is_new,
        "server": DEFAULT_HOST,
        "reality": {
            "host": DEFAULT_HOST,
            "port": 443,
            "sni": _SRV.get("reality_sni", "api.weatherapi.com"),
            "reality_public_key": REALITY_PUBLIC_KEY,
            "reality_short_id": REALITY_SHORT_ID,
            "flow": "xtls-rprx-vision"
        },
        "xhttp": {
            "host": DEFAULT_HOST,
            "port": 443,
            "sni": _SRV.get("sni", "example.com"),
            "path": _SRV.get("path", "/api/v1/telemetry"),
            "post_quantum_encryption": PQ_ENCRYPTION_KEY
        }
    }

class ProfileHTTPHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, data: dict):
        response_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(response_bytes)

    def _get_client_ip(self) -> str:
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        x_real = self.headers.get("X-Real-IP")
        if x_real:
            return x_real.strip()
        return self.client_address[0] if self.client_address else "127.0.0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in ("/api/v1/profile/health", "/health"):
            with db_lock:
                with get_db_connection() as conn:
                    cur = conn.execute("SELECT COUNT(*) AS total, SUM(is_active) AS active FROM vpn_profiles")
                    row = cur.fetchone()
                    total = row["total"] or 0
                    active = row["active"] or 0
            self._send_json(200, {
                "status": "ok",
                "total_profiles": total,
                "active_profiles": active,
                "time": datetime.now(timezone.utc).isoformat()
            })
            return

        if path == "/api/v1/profile":
            query = parse_qs(parsed.query)
            hwids = query.get("hwid")
            if not hwids or not hwids[0].strip():
                self._send_json(400, {"status": "error", "message": "Missing 'hwid' query parameter"})
                return

            hwid = hwids[0].strip().lower()
            with db_lock:
                with get_db_connection() as conn:
                    cur = conn.execute(
                        "SELECT uuid, client_name, os_info, created_at, last_seen, is_active FROM vpn_profiles WHERE hwid = ?",
                        (hwid,)
                    )
                    row = cur.fetchone()

            if not row:
                self._send_json(404, {"status": "error", "message": "Profile not found for this HWID"})
                return

            client_ip = self._get_client_ip()
            res = get_or_register_profile(hwid, client_ip=client_ip)
            self._send_json(200, res)
            return

        self._send_json(404, {"status": "error", "message": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in ("/api/v1/profile", "/api/v1/profile/register"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length == 0:
                    self._send_json(400, {"status": "error", "message": "Empty body"})
                    return
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
            except Exception as e:
                self._send_json(400, {"status": "error", "message": f"Malformed JSON: {e}"})
                return

            hwid = str(data.get("hwid", "")).strip().lower()
            if not hwid or len(hwid) < 6:
                self._send_json(400, {"status": "error", "message": "Invalid or missing 'hwid' (min 6 chars)"})
                return

            client_name = str(data.get("client_name", "")).strip()
            os_info = str(data.get("os", "")).strip()
            client_ip = self._get_client_ip()

            try:
                result = get_or_register_profile(hwid, client_name, os_info, client_ip)
                self._send_json(200, result)
            except Exception as e:
                logging.exception("Registration error: %s", e)
                self._send_json(500, {"status": "error", "message": f"Internal server error: {e}"})
            return

        self._send_json(404, {"status": "error", "message": "Not found"})

    def log_message(self, format, *args):
        logging.info("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)

def run_server():
    init_db()
    sync_xray_config()

    server = HTTPServer((SERVER_HOST, SERVER_PORT), ProfileHTTPHandler)
    logging.info("Nexus Profile Server listening on http://%s:%d", SERVER_HOST, SERVER_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        logging.info("Server stopped.")

if __name__ == "__main__":
    run_server()
