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
            max_proxies = 500
            if self.config:
                max_proxies = self.config.get('output.v2ray.max_proxies', 500)
            
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
        """Сохранить в формате Mihomo YAML для FlClash."""
        if not output_file or not configs:
            return 0
        
        try:
            max_proxies = 500
            if self.config:
                max_proxies = self.config.get('output.mihomo.max_proxies', 500)
            
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
        name_counter = {}
        
        for i, config in enumerate(configs):
            proxy_type = self._get_type(config)
            
            # Пропускаем неподдерживаемые типы
            if proxy_type not in ['vmess', 'vless', 'trojan']:
                continue
            
            name = self._generate_unique_name(config, name_counter)
            
            outbound = {
                "tag": f"{name}_{i}",
                "type": proxy_type,
            }
            
            if proxy_type == 'vmess':
                outbound["settings"] = {
                    "vnext": [{
                        "address": config.get('add', config.get('server', '')),
                        "port": int(config.get('port', 443)),
                        "users": [{
                            "id": config.get('id', ''),
                            "alterId": int(config.get('aid', 0))
                        }]
                    }]
                }
            
            elif proxy_type == 'vless':
                outbound["settings"] = {
                    "vnext": [{
                        "address": config.get('add', config.get('server', '')),
                        "port": int(config.get('port', 443)),
                        "users": [{
                            "id": config.get('id', ''),
                        }]
                    }]
                }
            
            elif proxy_type == 'trojan':
                outbound["settings"] = {
                    "servers": [{
                        "address": config.get('server', ''),
                        "port": int(config.get('port', 443)),
                        "password": config.get('password', ''),
                    }]
                }
            
            outbounds.append(outbound)
        
        return outbounds
    
    def _convert_to_mihomo(self, configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Конвертировать в Mihomo формат для FlClash."""
        proxies = []
        name_counter = {}
        
        for i, config in enumerate(configs):
            proxy_type = self._get_type(config)
            
            # Пропускаем неподдерживаемые типы
            if proxy_type not in ['vmess', 'vless', 'trojan', 'ss']:
                continue
            
            name = self._generate_unique_name(config, name_counter)
            
            # БАЗОВЫЕ ПАРАМЕТРЫ (обязательные для всех)
            proxy = {
                "name": name,
                "type": proxy_type,
                "server": config.get('add', config.get('server', '')),
                "port": config.get('port', 443),
            }
            
            try:
                proxy["port"] = int(proxy["port"])
            except (ValueError, TypeError):
                continue
            
            # VMESS конфигурация
            if proxy_type == 'vmess':
                proxy["uuid"] = config.get('id', '')
                proxy["alterId"] = int(config.get('aid', 0))
                proxy["cipher"] = config.get('cipher', 'auto')
                
                # TLS параметры
                if config.get('tls') == 'tls':
                    proxy["tls"] = True
                    proxy["servername"] = config.get('sni', config.get('add', ''))
                    proxy["skipCertVerify"] = True
            
            # VLESS конфигурация
            elif proxy_type == 'vless':
                proxy["uuid"] = config.get('id', '')
                proxy["flow"] = config.get('flow', '')
                
                # TLS параметры
                if config.get('tls') == 'tls':
                    proxy["tls"] = True
                    proxy["servername"] = config.get('sni', config.get('add', ''))
                    proxy["skipCertVerify"] = True
                
                # Reality параметры
                if config.get('reality'):
                    proxy["reality"] = True
                    proxy["realityOpts"] = {
                        "publicKey": config.get('reality', {}).get('public-key', ''),
                        "shortId": config.get('reality', {}).get('short-id', ''),
                    }
            
            # TROJAN конфигурация
            elif proxy_type == 'trojan':
                proxy["password"] = config.get('password', '')
                proxy["sni"] = config.get('sni', '')
                proxy["skipCertVerify"] = True
            
            # SS конфигурация
            elif proxy_type == 'ss':
                proxy["cipher"] = config.get('cipher', 'aes-256-gcm')
                proxy["password"] = config.get('password', '')
                proxy["plugin"] = config.get('plugin', '')
            
            if proxy.get('server'):  # Только если есть сервер
                proxies.append(proxy)
        
        return proxies
    
    def _generate_unique_name(self, config: Dict[str, Any], name_counter: Dict[str, int]) -> str:
        """Генерировать уникальное имя для прокси."""
        original_name = config.get('ps', config.get('name', 'proxy'))
        
        # Удаляем опасные символы
        name = original_name.replace('[', '').replace(']', '').strip()
        
        if not name:
            name = 'proxy'
        
        # Ограничиваем длину
        if len(name) > 50:
            name = name[:47] + "..."
        
        if name in name_counter:
            name_counter[name] += 1
            final_name = f"{name}_{name_counter[name]}"
        else:
            name_counter[name] = 0
            final_name = name
        
        return final_name
    
    def _get_type(self, config: Dict[str, Any]) -> str:
        """Получить тип прокси."""
        config_type = str(config.get('type', '')).lower()
        
        # Явно указанный тип
        if config_type in ['vmess', 'vless', 'trojan', 'ss', 'ssr']:
            return config_type
        
        # Определяем по полям
        if 'id' in config and 'aid' in config:
            return 'vmess'
        if 'id' in config and 'add' in config:
            return 'vless'
        if 'password' in config and 'server' in config and 'cipher' not in config:
            return 'trojan'
        if 'password' in config and 'cipher' in config:
            return 'ss'
        
        return 'unknown'
