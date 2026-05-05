import logging
import sys
from pathlib import Path
from typing import Optional


class CollectorLogger:
    """Логирование с потоковым выводом и файлом."""
    
    _instance: Optional['CollectorLogger'] = None
    _stats = {
        'downloaded': 0,
        'extracted': 0,
        'deduplicated': 0,
        'validated': 0,
        'checked_ok': 0,
        'checked_fail': 0,
        'final': 0,
    }
    
    def __new__(cls, log_file: Optional[str] = None, level: str = "INFO"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_logger(log_file, level)
        return cls._instance
    
    def _init_logger(self, log_file: Optional[str], level: str):
        self.logger = logging.getLogger('collector')
        self.logger.setLevel(getattr(logging, level.upper()))
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))
        
        handlers = [console_handler]
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(getattr(logging, level.upper()))
            handlers.append(file_handler)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        for handler in handlers:
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def info(self, msg: str):
        self.logger.info(msg)
    
    def warning(self, msg: str):
        self.logger.warning(msg)
    
    def error(self, msg: str):
        self.logger.error(msg)
    
    def debug(self, msg: str):
        self.logger.debug(msg)
    
    def increment_stat(self, stat_name: str, count: int = 1):
        if stat_name in self._stats:
            self._stats[stat_name] += count
    
    def get_stats(self) -> dict:
        return self._stats.copy()
    
    def log_stats(self):
        stats = self.get_stats()
        self.info("=" * 60)
        self.info("ИТОГОВАЯ СТАТИСТИКА:")
        self.info(f"  Скачано источников: {stats['downloaded']}")
        self.info(f"  Извлечено конфигов: {stats['extracted']}")
        self.info(f"  После дедупликации: {stats['deduplicated']}")
        self.info(f"  Прошло валидацию: {stats['validated']}")
        self.info(f"  Прошло проверку: {stats['checked_ok']}")
        self.info(f"  Не прошло проверку: {stats['checked_fail']}")
        self.info(f"  В итоговом файле: {stats['final']}")
        self.info("=" * 60)
