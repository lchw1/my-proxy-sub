# Proxy Config Collector

Модульная система сбора, проверки и сборки proxy-конфигов для V2Ray и Mihomo.

## Установка

```bash
git clone <repo>
cd proxy-config-collector
pip install -r requirements.txt
```

## Использование

```bash
python main.py
```

Результаты в:
- `output/v2ray_proxies.json` — V2Ray конфиг
- `output/mihomo_proxies.yaml` — Mihomo конфиг

## Конфигурация

Отредактируй `config.yaml`:

```yaml
sources:
  - url: "https://example.com/proxies.json"
    type: "json"
    timeout: 10

processing:
  chunk_size: 1000          # Размер батча
  max_candidates: 10000     # Макс. конфигов
  concurrent_checks: 5      # Параллельные проверки
  check_timeout: 5          # Таймаут проверки
```

## Этапы обработки

1. **Загрузка** — скачивание из источников
2. **Декодирование** — извлечение конфигов (JSON, YAML, Base64)
3. **Валидация** — проверка структуры
4. **Дедупликация** — удаление дубликатов
5. **Проверка** — тестирование работоспособности
6. **Сохранение** — формирование итоговых файлов

## Логирование

Логи в консоль и файл (`collector.log`).

Статистика по каждому этапу.

## CI/CD

`.github/workflows/collect.yml`:

```yaml
name: Collect Proxies
on:
  schedule:
    - cron: '0 */6 * * *'
jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python main.py
      - uses: EndBug/add-and-commit@v9
        with:
          add: 'output/'
          message: 'Update proxies'
          push: true
```

## Структура

```
proxy-config-collector/
├── config.yaml
├── requirements.txt
├── main.py
├── src/
│   ├── config.py
│   ├── logger.py
│   ├── loader.py
│   ├── decoder.py
│   ├── validator.py
│   ├── deduplicator.py
│   ├── checker.py
│   └── formatter.py
└── output/
    ├── v2ray_proxies.json
    └── mihomo_proxies.yaml
```
