import json
import yaml
import base64
import urllib.parse
from typing import List, Dict, Any, Optional
from src.logger import CollectorLogger


class ConfigDecoder:
    """Декодирование конфигов из различных форматов."""
    
    def __init__(self):
        self.logger = CollectorLogger()
    
    def decode_all(self, raw_data_list: List[tuple]) -> List[Dict[str, Any]]:
        """Декодировать все загруженные данные."""
        configs = []
        
        for url, content, content_type in raw_data_list:
            try:
                decoded = self._decode_by_type(content, content_type)
                if decoded:
                    configs.extend(decoded)
                    self.logger.debug(f"  Декодировано {len(decoded)} конфигов из {url}")
            except Exception as e:
                self.logger.error(f"  Ошибка при декодировании {url} ({content_type}): {e}")
        
        self.logger.increment_stat('extracted', len(configs))
        self.logger.info(f"Всего извлечено конфигов: {len(configs)}")
        return configs
    
    def _decode_by_type(self, content: str, content_type: str) -> List[Dict[str, Any]]:
        """Декодировать по типу."""
        if content_type == 'json':
            return self._decode_json(content)
        elif content_type == 'yaml':
            return self._decode_yaml(content)
        elif content_type == 'base64':
            return self._decode_base64_urls(content)
        elif content_type == 'base64_json':
            return self._decode_base64_json(content)
        elif content_type == 'base64_yaml':
            return self._decode_base64_yaml(content)
        else:
            self.logger.warning(f"Неизвестный тип: {content_type}")
            return []
    
    def _decode_base64_urls(self, content: str) -> List[Dict[str, Any]]:
        """Декодировать Base64 и парсить V2Ray URLs."""
        configs = []
        
        try:
            # Пытаемся декодировать весь контент как Base64
            content = content.strip()
            decoded = base64.b64decode(content).decode('utf-8')
            
            # Парсим как URL-ссылки
            return self._parse_proxy_urls(decoded)
        except Exception:
            # Если не получилось, пытаемся парсить построчно
            return self._parse_proxy_urls(content)
    
    def _parse_proxy_urls(self, content: str) -> List[Dict[str, Any]]:
        """Парсить V2Ray URL ссылки (vless://, vmess://, etc)."""
        configs = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Проверяем известные URL-схемы
            if line.startswith(('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://', 'http://', 'https://')):
                config = self._parse_url_proxy(line)
                if config:
                    configs.append(config)
            else:
                # Может быть это закодированная ссылка
                try:
                    decoded_line = base64.b64decode(line).decode('utf-8')
                    config = self._parse_url_proxy(decoded_line)
                    if config:
                        configs.append(config)
                except Exception:
                    continue
        
        return configs
    
    def _parse_url_proxy(self, url: str) -> Optional[Dict[str, Any]]:
        """Парсить одну V2Ray URL ссылку."""
        try:
            if url.startswith('vmess://'):
                return self._parse_vmess(url)
            elif url.startswith('vless://'):
                return self._parse_vless(url)
            elif url.startswith('trojan://'):
                return self._parse_trojan(url)
            elif url.startswith('ss://'):
                return self._parse_ss(url)
            elif url.startswith('ssr://'):
                return self._parse_ssr(url)
        except Exception as e:
            self.logger.debug(f"Failed to parse URL: {e}")
        
        return None
    
    def _parse_vmess(self, url: str) -> Optional[Dict[str, Any]]:
        """Парсить vmess:// URL."""
        try:
            # vmess://base64(JSON)
            if url.startswith('vmess://'):
                encoded = url[8:].split('#')[0]  # Удаляем имя после #
                try:
                    decoded = base64.b64decode(encoded).decode('utf-8')
                    config = json.loads(decoded)
                    return config
                except Exception:
                    return None
        except Exception:
            pass
        return None
    
    def _parse_vless(self, url: str) -> Optional[Dict[str, Any]]:
        """Парсить vless:// URL."""
        try:
            # vless://uuid@host:port/?param=value#name
            parsed = urllib.parse.urlparse(url)
            
            config = {
                'type': 'vless',
                'id': parsed.username,
                'add': parsed.hostname,
                'port': parsed.port or 443,
            }
            
            # Парсим параметры
            params = urllib.parse.parse_qs(parsed.query)
            for key, value in params.items():
                if value:
                    config[key] = value[0]
            
            # Имя из фрагмента
            if parsed.fragment:
                config['ps'] = urllib.parse.unquote(parsed.fragment)
            
            return config if config.get('id') and config.get('add') else None
        except Exception:
            pass
        return None
    
    def _parse_trojan(self, url: str) -> Optional[Dict[str, Any]]:
        """Парсить trojan:// URL."""
        try:
            # trojan://password@host:port/?param=value#name
            parsed = urllib.parse.urlparse(url)
            
            config = {
                'type': 'trojan',
                'password': parsed.username,
                'server': parsed.hostname,
                'port': parsed.port or 443,
            }
            
            # Парсим параметры
            params = urllib.parse.parse_qs(parsed.query)
            for key, value in params.items():
                if value:
                    config[key] = value[0]
            
            # Имя из фрагмента
            if parsed.fragment:
                config['ps'] = urllib.parse.unquote(parsed.fragment)
            
            return config if config.get('password') and config.get('server') else None
        except Exception:
            pass
        return None
    
    def _parse_ss(self, url: str) -> Optional[Dict[str, Any]]:
        """Парсить ss:// URL."""
        try:
            # ss://base64(cipher:password)@host:port#name
            parsed = urllib.parse.urlparse(url)
            
            # Декодируем cipher:password
            try:
                auth = base64.b64decode(parsed.username).decode('utf-8')
                cipher, password = auth.split(':', 1)
            except Exception:
                return None
            
            config = {
                'type': 'ss',
                'cipher': cipher,
                'password': password,
                'server': parsed.hostname,
                'port': parsed.port or 443,
            }
            
            # Имя из фрагмента
            if parsed.fragment:
                config['ps'] = urllib.parse.unquote(parsed.fragment)
            
            return config if config.get('cipher') and config.get('server') else None
        except Exception:
            pass
        return None
    
    def _parse_ssr(self, url: str) -> Optional[Dict[str, Any]]:
        """Парсить ssr:// URL."""
        try:
            # ssr://base64(host:port:protocol:cipher:obfs:password)
            if url.startswith('ssr://'):
                encoded = url[6:].split('#')[0]
                try:
                    decoded = base64.b64decode(encoded + '==').decode('utf-8')
                    parts = decoded.split(':')
                    
                    if len(parts) >= 6:
                        config = {
                            'type': 'ssr',
                            'server': parts[0],
                            'port': int(parts[1]),
                            'cipher': parts[3],
                            'password': parts[5],
                        }
                        return config
                except Exception:
                    pass
        except Exception:
            pass
        return None
    
    def _decode_json(self, content: str) -> List[Dict[str, Any]]:
        """Декодировать JSON."""
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                if 'proxies' in data and isinstance(data['proxies'], list):
                    return data['proxies']
                if 'items' in data and isinstance(data['items'], list):
                    return data['items']
                return [data]
            return []
        except json.JSONDecodeError as e:
            self.logger.debug(f"JSON decode error: {e}")
            return []
    
    def _decode_yaml(self, content: str) -> List[Dict[str, Any]]:
        """Декодировать YAML."""
        try:
            data = yaml.safe_load(content)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                if 'proxies' in data and isinstance(data['proxies'], list):
                    return data['proxies']
                if 'items' in data and isinstance(data['items'], list):
                    return data['items']
                return [data]
            return []
        except yaml.YAMLError as e:
            self.logger.debug(f"YAML decode error: {e}")
            return []
    
    def _decode_base64_json(self, content: str) -> List[Dict[str, Any]]:
        """Декодировать Base64 -> JSON."""
        try:
            decoded = base64.b64decode(content).decode('utf-8')
            return self._decode_json(decoded)
        except Exception as e:
            self.logger.debug(f"Base64+JSON decode error: {e}")
            return []
    
    def _decode_base64_yaml(self, content: str) -> List[Dict[str, Any]]:
        """Декодировать Base64 -> YAML."""
        try:
            decoded = base64.b64decode(content).decode('utf-8')
            return self._decode_yaml(decoded)
        except Exception as e:
            self.logger.debug(f"Base64+YAML decode error: {e}")
            return []
