import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

_SECRETS_CACHE = None

def get_secrets_path() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundled = Path(sys._MEIPASS) / 'secrets.json'
        if bundled.exists():
            return bundled
        exe_dir = Path(sys.executable).parent / 'secrets.json'
        if exe_dir.exists():
            return exe_dir

    project_root = Path(__file__).resolve().parent.parent
    root_secrets = project_root / 'secrets.json'
    if root_secrets.exists():
        return root_secrets

    return project_root / 'secrets.json'

def get_secrets() -> Dict[str, Any]:
    global _SECRETS_CACHE
    if _SECRETS_CACHE is not None:
        return _SECRETS_CACHE

    p = get_secrets_path()
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                _SECRETS_CACHE = json.load(f)
                return _SECRETS_CACHE
        except Exception:
            pass

    _SECRETS_CACHE = {
        'server': {
            'host': '127.0.0.1',
            'port': 443,
            'server_ip1': '127.0.0.1',
            'server_ip2': '127.0.0.1',
            'uuid': '00000000-0000-0000-0000-000000000000',
            'user': 'user',
            'pass': 'pass',
            'sni': 'example.com',
            'path': '/api/v1/telemetry',
            'reality_sni': 'api.weatherapi.com',
            'reality_public_key': '',
            'reality_short_id': '',
            'post_quantum_encryption': '',
            'remote_dns_host': '1.1.1.1',
            'remote_dns_port': 53
        },
        'api_base': 'https://example.com/api/v1',
        'links': {
            'telegram': 'https://t.me/',
            'website': 'https://example.com'
        }
    }
    return _SECRETS_CACHE
