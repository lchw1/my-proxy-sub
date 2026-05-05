#!/usr/bin/env python3
"""
Главный скрипт сбора, проверки и сборки proxy-конфигов.

Процесс:
1. Загрузить конфиги из источников
2. Декодировать из различных форматов
3. Валидировать структуру
4. Удалить дубликаты
5. Проверить работоспособность (батчами)
6. Сформировать итоговые файлы
"""

import sys
from pathlib import Path
from src.config import Config
from src.logger import CollectorLogger
from src.loader import ConfigLoader
from src.decoder import ConfigDecoder
from src.validator import ConfigValidator
from src.deduplicator import ConfigDeduplicator
from src.checker import ConfigChecker
from src.formatter import ConfigFormatter


def main():
    """Главный процесс."""
    
    try:
        config = Config("config.yaml")
    except FileNotFoundError:
        print("ERROR: config.yaml not found!")
        sys.exit(1)
    
    logger = CollectorLogger(config.log_file, config.log_level)
    logger.info("=" * 60)
    logger.info("Начало сбора proxy-конфигов")
    logger.info("=" * 60)
    
    # Этап 1: Загрузка
    logger.info("\n[1/6] Загрузка источников...")
    loader = ConfigLoader(config)
    raw_data = loader.load_all_sources()
    
    if not raw_data:
        logger.error("Нет загруженных данных!")
        return False
    
    # Этап 2: Декодирование
    logger.info("\n[2/6] Декодирование конфигов...")
    decoder = ConfigDecoder()
    configs = decoder.decode_all(raw_data)
    
    if not configs:
        logger.error("Нет декодированных конфигов!")
        return False
    
    if len(configs) > config.max_candidates:
        logger.warning(f"Ограничено до {config.max_candidates} конфигов (было {len(configs)})")
        configs = configs[:config.max_candidates]
    
    # Этап 3: Валидация
    logger.info("\n[3/6] Валидация структуры...")
    validator = ConfigValidator(config)
    configs = validator.validate_and_filter(configs)
    
    if not configs:
        logger.error("Нет валидных конфигов!")
        return False
    
    # Этап 4: Дедупликация
    logger.info("\n[4/6] Удаление дубликатов...")
    deduplicator = ConfigDeduplicator()
    configs = deduplicator.deduplicate(configs)
    
    if not configs:
        logger.error("Нет конфигов после дедупликации!")
        return False
    
    # Этап 5: Проверка работоспособности (батчами)
    logger.info("\n[5/6] Проверка работоспособности...")
    checker = ConfigChecker(config)
    working_configs = []
    
    chunk_size = config.chunk_size
    total_chunks = (len(configs) + chunk_size - 1) // chunk_size
    
    for chunk_num in range(total_chunks):
        start_idx = chunk_num * chunk_size
        end_idx = min(start_idx + chunk_size, len(configs))
        chunk = configs[start_idx:end_idx]
        
        logger.info(f"  Чанк {chunk_num + 1}/{total_chunks} ({len(chunk)} конфигов)...")
        
        working, failed = checker.check_batch(chunk)
        working_configs.extend(working)
        
        logger.debug(f"    ✓ Работают: {len(working)}, ✗ Не работают: {len(failed)}")
    
    logger.info(f"Всего работающих конфигов: {len(working_configs)}")
    
    if not working_configs:
        logger.warning("Нет работающих конфигов!")
    
    # Этап 6: Сохранение
    logger.info("\n[6/6] Сохранение итоговых файлов...")
    formatter = ConfigFormatter()
    
    v2ray_count = formatter.save_v2ray(working_configs, config.v2ray_output)
    mihomo_count = formatter.save_mihomo(working_configs, config.mihomo_output)
    
    logger.log_stats()
    logger.info("Процесс завершен успешно!")
    logger.info("=" * 60)
    
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
