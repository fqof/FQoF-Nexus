import json
import logging
import os
import platform
import socket
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional
from gui.secrets import get_secrets

def _get_fallback_uuid() -> str:
    return get_secrets().get('server', {}).get('uuid', '00000000-0000-0000-0000-000000000000')

def _get_api_endpoint() -> str:
    s = get_secrets()
    base = s.get('api_base', 'https://example.com/api/v1').rstrip('/')
    return f'{base}/profile'

logger = logging.getLogger('FQoF_Nexus.ProfileManager')

def get_system_hwid() -> str:
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography') as key:
                guid, _ = winreg.QueryValueEx(key, 'MachineGuid')
                if guid and len(str(guid).strip()) > 8:
                    return str(guid).strip().lower()
        except Exception as e:
            logger.warning(f'Could not read MachineGuid from registry: {e}')

    try:
        import uuid
        node = uuid.getnode()
        import hashlib
        return hashlib.sha256(f'hwid-node-{node}'.encode()).hexdigest()[:36]
    except Exception:
        return 'generic-client-guid'

def get_cache_dir() -> Path:
    appdata = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
    if appdata:
        p = Path(appdata) / 'FQoF_Nexus'
    else:
        p = Path.home() / '.config' / 'fqof_nexus'
    p.mkdir(parents=True, exist_ok=True)
    return p

class ProfileManager:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.hwid = get_system_hwid()
        self.cache_file = get_cache_dir() / 'profile.json'
        self.profile_data: Dict[str, Any] = self._load_cache()
        self.uuid = self.profile_data.get('uuid', _get_fallback_uuid())

    @classmethod
    def get_instance(cls) -> 'ProfileManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _load_cache(self) -> Dict[str, Any]:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and data.get('hwid') == self.hwid and data.get('uuid'):
                        return data
            except Exception as e:
                logger.warning(f'Failed to read cached profile: {e}')
        return {
            'hwid': self.hwid,
            'uuid': _get_fallback_uuid()
        }

    def _save_cache(self, data: Dict[str, Any]):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f'Failed to write profile cache: {e}')

    def fetch_or_register(self, timeout: float = 4.0) -> Dict[str, Any]:
        try:
            client_name = socket.gethostname()
            os_info = f'{platform.system()} {platform.release()} ({platform.version()})'
            payload = {
                'hwid': self.hwid,
                'client_name': client_name,
                'os': os_info
            }
            req = urllib.request.Request(
                _get_api_endpoint(),
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'FQoF-Nexus-Client/2.0'
                },
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    resp_data = json.loads(response.read().decode('utf-8'))
                    if resp_data.get('status') == 'success' and resp_data.get('uuid'):
                        self.profile_data.update(resp_data)
                        self.uuid = resp_data['uuid']
                        self._save_cache(self.profile_data)
                        logger.info(f'Profile synchronized with VPS. Assigned UUID: {self.uuid}')
                        return self.profile_data
        except Exception as e:
            logger.warning(f'Server profile registration attempt failed ({e}). Using cached UUID: {self.uuid}')

        return self.profile_data

    def get_uuid(self) -> str:
        return self.uuid or _get_fallback_uuid()

    def get_hwid_short(self) -> str:
        h = self.hwid
        if len(h) > 16:
            return f'{h[:8]}...{h[-6:]}'
        return h
