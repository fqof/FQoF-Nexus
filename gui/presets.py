from typing import Dict, Any
from gui.secrets import get_secrets

def _build_presets() -> Dict[str, Dict[str, Any]]:
    s = get_secrets()
    srv = s.get('server', {})
    host = srv.get('host', '127.0.0.1')
    port = srv.get('port', 443)
    sni = srv.get('sni', 'example.com')
    path = srv.get('path', '/api/v1/telemetry')
    pq_key = srv.get('post_quantum_encryption', '')
    reality_sni = srv.get('reality_sni', 'api.weatherapi.com')
    reality_pub = srv.get('reality_public_key', '')
    reality_sid = srv.get('reality_short_id', '')

    return {
        'stealth_ghost': {
            'name': '🕶️ ТСПУ Ghost',
            'description': 'Максимальная скрытность перед ТСПУ. Постквантовое шифрование ML-KEM-768/X25519, микрофрагментация TLS ClientHello (1-3 байта), рандомизация XHTTP Padding и ротация сокетов xmux.',
            'config': {
                'mode': 'vless_xhttp',
                'remote_proxy': {
                    'host': host,
                    'port': port,
                    'sni': sni,
                    'path': path,
                    'post_quantum_encryption': pq_key
                },
                'dpi': {
                    'enabled': False
                }
            }
        },
        'vless_reality': {
            'name': '⚡ REALITY',
            'description': 'Альтернативная маскировка. Рекомендуется при избирательных блокировках стандартных сертификатов.',
            'config': {
                'mode': 'vless_reality',
                'remote_proxy': {
                    'host': host,
                    'port': port,
                    'sni': reality_sni,
                    'reality_public_key': reality_pub,
                    'reality_short_id': reality_sid,
                    'post_quantum_encryption': pq_key
                },
                'dpi': {
                    'enabled': False
                }
            }
        }
    }

PRESETS = _build_presets()
