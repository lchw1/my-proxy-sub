import ipaddress
from typing import Dict, Any, Optional
from src.logger import CollectorLogger
from src.config import Config


class ConfigValidator:
    """Валидация структуры конфигов."""
    
    REQUIRED_FIELDS = {
        'http': ['server', 'port'],
        'https': ['server', 'port'],
        'socks5': ['server', 'port'],
        'socks4': ['server', 'port'],
        'vmess': ['add', 'port', 'id', 'aid'],
        'vless': ['add', 'port', 'id'],
        'trojan': ['server', 'port', 'password'],
        'ss': ['server', 'port', 'cipher', 'password'],
        'ssr': ['server', 'port', 'cipher', 'password'],
    }
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = CollectorLogger()
    
    def validate_and_filter(self, configs: list) -> list:
        """Валидировать конфиги и отфильтровать битые."""
        valid = []
        invalid_count = 0
        
        for config in configs:
            if self._is_valid(config):
                valid.append(config)
            else:
                invalid_count += 1
        
        self.logger.increment_stat('validated', len(valid))
        self.logger.info(f"Валидация: {len(valid)} валидных, {invalid_count} отбраковано")
        return valid
    
    def _is_valid(self, config: Dict[str, Any]) -> bool:
        """Проверить конфиг на корректность."""
        if not isinstance(config, dict):
            return False
        
        proxy_type = self._get_proxy_type(config)
        if not proxy_type:
            return False
        
        required = self.REQUIRED_FIELDS.get(proxy_type, [])
        for field in required:
            if field not in config or not config[field]:
                return False
        
        host = config.get('server') or config.get('add')
        if not host:
            return False
        
        if not self._is_valid_host(host):
            return False
        
        port = config.get('port')
        if not self._is_valid_port(port):
            return False
        
        return True
    
    def _get_proxy_type(self, config: Dict[str, Any]) -> Optional[str]:
        """Определить тип прокси."""
        for proxy_type in ['type', 'protocol', 'ps']:
            if proxy_type in config:
                ptype = str(config[proxy_type]).lower()
                if ptype in self.REQUIRED_FIELDS:
                    return ptype
        
        if 'id' in config and 'aid' in config:
            return 'vmess'
        if 'id' in config and 'add' in config:
            return 'vless'
        if 'password' in config and 'cipher' in config:
            return 'ss'
        if 'server' in config and 'port' in config:
            if 'password' in config:
                return 'trojan'
            return 'http'
        
        return None
    
    def _is_valid_host(self, host: str) -> bool:
        """Проверить хост."""
        if not isinstance(host, str) or not host:
            return False
        
        if self.config.skip_localhost:
            if host.lower() in ['localhost', '127.0.0.1', '::1']:
                return False
        
        if self.config.skip_private_ips:
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback:
                    return False
            except ValueError:
                pass
        
        return True
    
    def _is_valid_port(self, port: Any) -> bool:
        """Проверить порт."""
        try:
            p = int(port)
            return self.config.get('filtering.min_port', 1) <= p <= self.config.get('filtering.max_port', 65535)
        except (ValueError, TypeError):
            return False
