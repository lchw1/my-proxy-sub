import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional


class Config:
    """Конфигурация приложения из YAML."""
    
    def __init__(self, config_file: str = "config.yaml"):
        self.config_path = Path(config_file)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.data = yaml.safe_load(f) or {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """Получить значение по пути (поддерживает точечную нотацию)."""
        keys = key.split('.')
        value = self.data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        return value if value is not None else default
    
    @property
    def sources(self) -> List[Dict[str, Any]]:
        return self.get('sources', [])
    
    @property
    def chunk_size(self) -> int:
        return self.get('processing.chunk_size', 1000)
    
    @property
    def max_candidates(self) -> int:
        return self.get('processing.max_candidates', 10000)
    
    @property
    def concurrent_checks(self) -> int:
        return self.get('processing.concurrent_checks', 5)
    
    @property
    def check_timeout(self) -> int:
        return self.get('processing.check_timeout', 5)
    
    @property
    def retry_count(self) -> int:
        return self.get('processing.retry_count', 1)
    
    @property
    def skip_localhost(self) -> bool:
        return self.get('filtering.skip_localhost', True)
    
    @property
    def skip_private_ips(self) -> bool:
        return self.get('filtering.skip_private_ips', True)
    
    @property
    def log_file(self) -> Optional[str]:
        return self.get('logging.file')
    
    @property
    def log_level(self) -> str:
        return self.get('logging.level', 'INFO')
    
    @property
    def v2ray_output(self) -> Optional[str]:
        if self.get('output.v2ray.enabled', True):
            return self.get('output.v2ray.file')
        return None
    
    @property
    def mihomo_output(self) -> Optional[str]:
        if self.get('output.mihomo.enabled', True):
            return self.get('output.mihomo.file')
        return None
