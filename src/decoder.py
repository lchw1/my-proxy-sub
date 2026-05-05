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
            # Пытаемся декодировать всю строку как Base64
            decoded = self._try_decode_base64(content)
            if decoded:
                # Результат может быть список конфигов, разделённых \n
                return self._parse_config_string(decoded)
            return []
        elif content_type == 'base64_json':
            return self._decode_base64_json(content)
        elif content_type == 'base64_yaml':
            return self._decode_base64_yaml(content)
        else:
            self.logger.warning(f"Неизвестный тип: {content_type}")
            return []
    
    def _try_decode_base64(self, content: str) -> Optional[str]:
        """Попытаться декодировать Base64."""
        try:
            # Удаляем пробелы и переносы строк
            content = content.strip()
            decoded = base64.b64decode(content).decode('utf-8')
            return decoded
        except Exception:
            return None
    
    def _parse_config_string(self, content: str) -> List[Dict[str, Any]]:
        """Парсить строку конфигов (может быть JSON, YAML или строки через \\n)."""
        configs = []
        
        # Пытаемся парсить как JSON массив
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return [c for c in data if isinstance(c, dict)]
            elif isinstance(data, dict):
                if 'proxies' in data and isinstance(data['proxies'], list):
                    return data['proxies']
                if 'items' in data and isinstance(data['items'], list):
                    return data['items']
                return [data]
        except json.JSONDecodeError:
            pass
        
        # Пытаемся парсить как YAML
        try:
            data = yaml.safe_load(content)
            if isinstance(data, list):
                return [c for c in data if isinstance(c, dict)]
            elif isinstance(data, dict):
                if 'proxies' in data and isinstance(data['proxies'], list):
                    return data['proxies']
                if 'items' in data and isinstance(data['items'], list):
                    return data['items']
                return [data]
        except yaml.YAMLError:
            pass
        
        # Если не JSON и не YAML, пытаемся парсить как строки через \n
        # Каждая строка может быть Base64-кодированным конфигом
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Пытаемся декодировать каждую строку как Base64
            try:
                decoded_line = base64.b64decode(line).decode('utf-8')
                try:
                    config = json.loads(decoded_line)
                    if isinstance(config, dict):
                        configs.append(config)
                except json.JSONDecodeError:
                    try:
                        config = yaml.safe_load(decoded_line)
                        if isinstance(config, dict):
                            configs.append(config)
                    except yaml.YAMLError:
                        pass
            except Exception:
                continue
        
        return configs
    
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
