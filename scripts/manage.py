#!/usr/bin/env python3
"""
FQoF Nexus Profiles Manager CLI
Usage:
    python3 manage.py list
    python3 manage.py add <hwid> [client_name]
    python3 manage.py delete <hwid>
    python3 manage.py sync
"""

import sys
import os
import sqlite3
import json
import uuid
from datetime import datetime, timezone

DB_PATH = "/wtf/vpn/vpn_profiles.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def cmd_list():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} does not exist yet.")
        return
    with get_db() as conn:
        cur = conn.execute("SELECT id, hwid, uuid, client_name, os_info, created_at, last_seen, last_ip, is_active FROM vpn_profiles ORDER BY id ASC")
        rows = cur.fetchall()
    
    print(f"\n{'ID':<4} | {'HWID':<34} | {'UUID':<36} | {'NAME':<15} | {'LAST SEEN':<19} | {'IP':<15}")
    print("-" * 135)
    for r in rows:
        created = r['created_at'][:19] if r['created_at'] else ''
        last_seen = r['last_seen'][:19] if r['last_seen'] else ''
        status_marker = "" if r['is_active'] else " [INACTIVE]"
        name = (r['client_name'] or '') + status_marker
        print(f"{r['id']:<4} | {r['hwid']:<34} | {r['uuid']:<36} | {name:<15} | {last_seen:<19} | {r['last_ip']:<15}")
    print(f"\nTotal profiles: {len(rows)}\n")

def cmd_add(hwid, name=""):
    import server_profile_daemon
    res = server_profile_daemon.get_or_register_profile(hwid, client_name=name)
    print(json.dumps(res, indent=2))

def cmd_sync():
    import server_profile_daemon
    server_profile_daemon.init_db()
    ok = server_profile_daemon.sync_xray_config()
    print("Sync result:", "OK" if ok else "FAILED")

def cmd_delete(hwid):
    clean_hwid = hwid.strip().lower()
    with get_db() as conn:
        conn.execute("DELETE FROM vpn_profiles WHERE hwid = ?", (clean_hwid,))
        conn.commit()
    print(f"Deleted {clean_hwid} from DB. Running sync...")
    cmd_sync()

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1].lower()
    if cmd == "list":
        cmd_list()
    elif cmd == "add" and len(sys.argv) >= 3:
        name = sys.argv[3] if len(sys.argv) > 3 else ""
        cmd_add(sys.argv[2], name)
    elif cmd == "delete" and len(sys.argv) >= 3:
        cmd_delete(sys.argv[2])
    elif cmd == "sync":
        cmd_sync()
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
