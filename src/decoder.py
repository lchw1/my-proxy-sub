import json
import yaml
import base64
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
            return self._decode_base64(content)
        elif content_type == 'base64_json':
            return self._decode_base64_json(content)
        elif content_type == 'base64_yaml':
            return self._decode_base64_yaml(content)
        else:
            self.logger.warning(f"Неизвестный тип: {content_type}")
            return []
    
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
    
    def _decode_base64(self, content: str) -> List[Dict[str, Any]]:
        """Декодировать Base64."""
        try:
            decoded = base64.b64decode(content).decode('utf-8')
            return self._decode_json(decoded) or self._decode_yaml(decoded)
        except Exception as e:
            self.logger.debug(f"Base64 decode error: {e}")
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
