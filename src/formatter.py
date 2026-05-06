import json
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path
from src.logger import CollectorLogger
from src.config import Config


class ConfigFormatter:
    """Форматирование итоговых конфигов."""
    
    def __init__(self, config: Optional[Config] = None):
        self.logger = CollectorLogger()
        self.config = config
    
    def save_v2ray(self, configs: List[Dict[str, Any]], output_file: Optional[str]) -> int:
        """Сохранить в формате V2Ray JSON."""
        if not output_file or not configs:
            return 0
        
        try:
            # Получаем максимум прокси из конфига
            max_proxies = 500
            if self.config:
                max_proxies = self.config.get('output.v2ray.max_proxies', 500)
            
            # Срезаем до максимума
            configs = configs[:max_proxies]
            
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            
            v2ray_format = {
                "outbounds": self._convert_to_v2ray(configs)
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(v2ray_format, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"V2Ray конфиг сохранен: {output_file} ({len(configs)} прокси)")
            self.logger.increment_stat('final', len(configs))
            return len(configs)
        
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении V2Ray: {e}")
            return 0
    
    def save_mihomo(self, configs: List[Dict[str, Any]], output_file: Optional[str]) -> int:
        """Сохранить в формате Mihomo YAML."""
        if not output_file or not configs:
            return 0
        
        try:
            # Получаем максимум прокси из конфига
            max_proxies = 500
            if self.config:
                max_proxies = self.config.get('output.mihomo.max_proxies', 500)
            
            # Срезаем до максимума
            configs = configs[:max_proxies]
            
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            
            mihomo_format = {
                "proxies": self._convert_to_mihomo(configs)
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                yaml.dump(mihomo_format, f, default_flow_style=False, allow_unicode=True)
            
            self.logger.info(f"Mihomo конфиг сохранен: {output_file} ({len(configs)} прокси)")
            self.logger.increment_stat('final', len(configs))
            return len(configs)
        
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении Mihomo: {e}")
            return 0
    
    def _convert_to_v2ray(self, configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Конвертировать в V2Ray формат."""
        outbounds = []
        
        for i, config in enumerate(configs):
            proxy_type = self._get_type(config)
            
            outbound = {
                "tag": f"proxy_{i}",
                "type": proxy_type,
            }
            
            if proxy_type in ['vmess', 'vless']:
                outbound["settings"] = {
                    "vnext": [{
                        "address": config.get('add', config.get('server')),
                        "port": int(config.get('port', 443)),
                        "users": [{
                            "id": config.get('id', ''),
                        }]
                    }]
                }
            elif proxy_type == 'trojan':
                outbound["settings"] = {
                    "servers": [{
                        "address": config.get('server'),
                        "port": int(config.get('port', 443)),
                        "password": config.get('password', ''),
                    }]
                }
            
            outbounds.append(outbound)
        
        return outbounds
    
    def _convert_to_mihomo(self, configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Конвертировать в Mihomo формат."""
        proxies = []
        
        for i, config in enumerate(configs):
            proxy_type = self._get_type(config)
            
            proxy = {
                "name": config.get('ps', f"proxy_{i}"),
                "type": proxy_type,
                "server": config.get('add', config.get('server')),
                "port": int(config.get('port', 443)),
            }
            
            if proxy_type in ['vmess', 'vless']:
                proxy["uuid"] = config.get('id', '')
                if 'aid' in config:
                    proxy["alterId"] = config['aid']
            elif proxy_type == 'trojan':
                proxy["password"] = config.get('password', '')
            elif proxy_type in ['ss', 'ssr']:
                proxy["cipher"] = config.get('cipher', '')
                proxy["password"] = config.get('password', '')
            
            proxies.append(proxy)
        
        return proxies
    
    def _get_type(self, config: Dict[str, Any]) -> str:
        """Получить тип прокси."""
        if 'type' in config:
            return str(config['type']).lower()
        if 'id' in config and 'aid' in config:
            return 'vmess'
        if 'id' in config:
            return 'vless'
        if 'password' in config and 'cipher' in config:
            return 'ss'
        return 'http'
