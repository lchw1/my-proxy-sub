from typing import Dict, Any, Set, List
from src.logger import CollectorLogger


class ConfigDeduplicator:
    """Удаление дубликатов конфигов."""
    
    def __init__(self):
        self.logger = CollectorLogger()
    
    def deduplicate(self, configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Удалить дубликаты по уникальному ключу."""
        seen: Set[str] = set()
        unique = []
        duplicates = 0
        
        for config in configs:
            key = self._get_unique_key(config)
            if key not in seen:
                seen.add(key)
                unique.append(config)
            else:
                duplicates += 1
        
        self.logger.increment_stat('deduplicated', len(unique))
        self.logger.info(f"Дедупликация: {len(unique)} уникальных, {duplicates} дубликатов удалено")
        return unique
    
    def _get_unique_key(self, config: Dict[str, Any]) -> str:
        """Получить уникальный ключ конфига."""
        server = config.get('server') or config.get('add', '')
        port = config.get('port', '')
        protocol_id = config.get('id', '')
        
        return f"{server}:{port}:{protocol_id}"
