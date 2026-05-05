import requests
from typing import List, Dict, Any, Optional
from src.logger import CollectorLogger
from src.config import Config


class ConfigLoader:
    """Загрузка конфигов из источников."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = CollectorLogger()
    
    def load_all_sources(self) -> List[tuple]:
        """Загрузить все источники. Возвращает список (url, content, content_type)."""
        results = []
        sources = self.config.sources
        
        if not sources:
            self.logger.warning("Источники не найдены в конфиге")
            return results
        
        for source in sources:
            url = source.get('url')
            source_type = source.get('type', 'json')
            timeout = source.get('timeout', 10)
            
            try:
                self.logger.info(f"Загрузка: {url} (тип: {source_type})")
                content = self._fetch_url(url, timeout)
                
                if content:
                    results.append((url, content, source_type))
                    self.logger.info(f"  ✓ Загружено {len(content)} байт")
                    self.logger.increment_stat('downloaded')
                else:
                    self.logger.warning(f"  ✗ Пусто")
            
            except requests.Timeout:
                self.logger.error(f"  ✗ Таймаут при загрузке {url}")
            except requests.RequestException as e:
                self.logger.error(f"  ✗ Ошибка при загрузке {url}: {e}")
            except Exception as e:
                self.logger.error(f"  ✗ Неожиданная ошибка при загрузке {url}: {e}")
        
        return results
    
    def _fetch_url(self, url: str, timeout: int = 10) -> Optional[str]:
        """Загрузить URL с таймаутом."""
        response = requests.get(url, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        return response.text
