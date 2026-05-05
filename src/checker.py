import asyncio
import aiohttp
from typing import Dict, Any, List, Tuple
from src.logger import CollectorLogger
from src.config import Config


class ConfigChecker:
    """Проверка работоспособности конфигов."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = CollectorLogger()
    
    def check_batch(self, configs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Проверить батч конфигов асинхронно. Возвращает (working, failed)."""
        if not configs:
            return [], []
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            working, failed = loop.run_until_complete(self._check_async(configs))
            return working, failed
        finally:
            loop.close()
    
    async def _check_async(self, configs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Асинхронная проверка конфигов."""
        working = []
        failed = []
        
        semaphore = asyncio.Semaphore(self.config.concurrent_checks)
        
        tasks = []
        for config in configs:
            task = self._check_single(config, semaphore)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for config, result in zip(configs, results):
            if isinstance(result, Exception):
                failed.append(config)
                self.logger.debug(f"  Проверка {self._get_config_desc(config)} failed: {result}")
            elif result:
                working.append(config)
                self.logger.increment_stat('checked_ok')
            else:
                failed.append(config)
                self.logger.increment_stat('checked_fail')
        
        return working, failed
    
    async def _check_single(self, config: Dict[str, Any], semaphore: asyncio.Semaphore) -> bool:
        """Проверить один конфиг."""
        async with semaphore:
            timeout = aiohttp.ClientTimeout(total=self.config.check_timeout)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    server = config.get('server') or config.get('add')
                    port = config.get('port')
                    
                    try:
                        async with session.get(
                            f'http://{server}:{port}',
                            timeout=aiohttp.ClientTimeout(total=self.config.check_timeout),
                            allow_redirects=False
                        ) as resp:
                            return resp.status < 500
                    except (asyncio.TimeoutError, aiohttp.ClientError):
                        return False
            except Exception:
                return False
    
    def _get_config_desc(self, config: Dict[str, Any]) -> str:
        """Получить описание конфига для логов."""
        server = config.get('server') or config.get('add', 'unknown')
        port = config.get('port', 'unknown')
        return f"{server}:{port}"
