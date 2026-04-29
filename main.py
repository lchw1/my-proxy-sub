import base64
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

# ==================== Конфигурация ====================

load_dotenv()

CONFIG_FILE = Path("sources.json")
CACHE_TIMESTAMP_FILE = Path(".cache_timestamp")
REPORT_FILE = Path("report.txt")
REPORT_JSON_FILE = Path("report.json")
LOG_FILE = Path("proxy_collector.log")
REPORTS_DIR = Path("reports")

# Создаем папку для отчетов
REPORTS_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "source_repos": [
        "https://github.com/igareck/vpn-configs-for-russia",
        "https://github.com/kort0881/vpn-vless-configs-russia",
        "https://github.com/yebekhe/TelegramV2rayCollector",
    ],
    "direct_urls": [],
    "sub_limit": 550,
    "clash_limit": 500,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 25))
PING_TIMEOUT = int(os.getenv("PING_TIMEOUT", 5))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 5))
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", 6))
TEST_PROXIES = os.getenv("TEST_PROXIES", "false").lower() == "true"
PING_URL = os.getenv("PING_URL", "http://www.gstatic.com/generate_204")
TEST_SAMPLE_SIZE = int(os.getenv("TEST_SAMPLE_SIZE", 50))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

ALLOWED_EXTS = {".txt", ".sub", ".base64", ".b64", ".list"}
SKIP_NAME_PARTS = {
    "readme", "license", "changelog", "requirements", "setup",
    "example", "sample", "test", "demo", "package-lock", "pyproject",
    "gitignore", "dockerfile", "makefile", "yml", "yaml", "json", "md",
}
CONFIG_DIRS = {"config", "configs", "conf", "configuration"}
NODE_RE = re.compile(r"vless://[^\s\r\n'\"<>]+", re.IGNORECASE)

# ==================== Логирование ====================

def setup_logging():
    """Настройка логирования в файл и консоль"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Файловый обработчик
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)

    # Консольный обработчик
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    # Форматер
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)-8s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


logger = setup_logging()


# ==================== Пользовательские исключения ====================

class ProxyCollectorError(Exception):
    """Базовое исключение для сборщика прокси"""
    pass


# ==================== Работа с конфигурацией ====================

def load_config() -> Dict:
    """Загружает конфигурацию из файла или создает дефолтную"""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = DEFAULT_CONFIG.copy()
                for key in ("source_repos", "direct_urls", "sub_limit", "clash_limit"):
                    if key in data:
                        cfg[key] = data[key]
                cfg["source_repos"] = [
                    str(x).strip() for x in cfg.get("source_repos", []) if str(x).strip()
                ]
                cfg["direct_urls"] = [
                    str(x).strip() for x in cfg.get("direct_urls", []) if str(x).strip()
                ]
                cfg["sub_limit"] = int(cfg.get("sub_limit", 550))
                cfg["clash_limit"] = int(cfg.get("clash_limit", 500))
                return cfg
        except Exception as e:
            logger.warning(f"Ошибка при загрузке конфига: {e}, используется дефолтный")

    CONFIG_FILE.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Создан файл конфигурации: {CONFIG_FILE}")
    return DEFAULT_CONFIG.copy()


def should_refresh_cache() -> bool:
    """Проверяет, нужно ли обновить кэш"""
    if not CACHE_TIMESTAMP_FILE.exists():
        return True

    try:
        last_run_str = CACHE_TIMESTAMP_FILE.read_text().strip()
        last_run = datetime.fromisoformat(last_run_str)
        elapsed = datetime.now() - last_run
        return elapsed > timedelta(hours=CACHE_TTL_HOURS)
    except Exception:
        return True


def update_cache_timestamp():
    """Обновляет временную метку кэша"""
    CACHE_TIMESTAMP_FILE.write_text(datetime.now().isoformat())


# ==================== HTTP запросы ====================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
def fetch_text(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    """Загружает текстовый контент с повторами при ошибке"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
        logger.debug(f"SKIP {url} — HTTP {r.status_code}")
    except Exception as e:
        logger.debug(f"ERR  {url} — {e}")
    return ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
def fetch_json(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    """Загружает JSON с повторами при ошибке"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        logger.debug(f"SKIP {url} — HTTP {r.status_code}")
    except Exception as e:
        logger.debug(f"ERR  {url} — {e}")
    return None


def test_proxy_ping(vless_url: str) -> Tuple[bool, float]:
    """
    Тестирует прокси отправкой пинга.
    Возвращает (успех, пинг_в_мс)
    """
    try:
        parsed = urllib.parse.urlsplit(vless_url)
        if parsed.scheme.lower() != "vless" or not parsed.hostname or not parsed.port:
            return False, float('inf')

        # Попытка подключиться к серверу прокси
        start = time.time()
        sock = __import__('socket').socket(__import__('socket').AF_INET, __import__('socket').SOCK_STREAM)
        sock.settimeout(PING_TIMEOUT)
        try:
            sock.connect((parsed.hostname, parsed.port))
            sock.close()
            elapsed = (time.time() - start) * 1000
            return True, elapsed
        except Exception:
            return False, float('inf')
    except Exception:
        return False, float('inf')


# ==================== Парсинг GitHub ====================

def github_owner_repo(repo_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Извлекает owner и repo из GitHub URL"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$", repo_url.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def is_probably_source_file(path: str) -> bool:
    """Проверяет, является ли файл потенциальным источником конфигов"""
    lower = path.lower()
    name = Path(lower).name
    ext = Path(name).suffix

    if ext not in ALLOWED_EXTS:
        return False

    if any(part in lower for part in SKIP_NAME_PARTS):
        return False

    return True


def is_config_directory(path: str) -> bool:
    """Проверяет, является ли папка папкой конфигураций"""
    lower = path.lower()
    parts = Path(lower).parts

    for part in parts:
        if part in CONFIG_DIRS:
            return True

    return any(part in lower for part in CONFIG_DIRS)


def raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    """Генерирует URL для сырого файла на GitHub"""
    safe_path = urllib.parse.quote(path, safe="/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{safe_path}"


def discover_github_files(repo_url: str) -> List[str]:
    """Обнаруживает файлы конфигов в репозитории (приоритет папкам конфигов)"""
    owner, repo = github_owner_repo(repo_url)
    if not owner or not repo:
        return []

    info = fetch_json(f"https://api.github.com/repos/{owner}/{repo}")
    if not isinstance(info, dict):
        return []

    branch = info.get("default_branch") or "main"
    tree = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")

    urls = []
    config_dir_urls = []

    if isinstance(tree, dict) and isinstance(tree.get("tree"), list):
        for item in tree["tree"]:
            if item.get("type") != "blob":
                continue
            path = item.get("path") or ""

            # Приоритет: файлы в папках конфигов
            if is_config_directory(path):
                if is_probably_source_file(path):
                    config_dir_urls.append(raw_url(owner, repo, branch, path))
            elif is_probably_source_file(path):
                urls.append(raw_url(owner, repo, branch, path))

        # Возвращаем файлы из папок конфигов в приоритете
        return config_dir_urls + urls

    # Fallback: рекурсивный API содержимого
    return discover_github_files_contents(owner, repo, "", branch)


def discover_github_files_contents(
    owner: str, repo: str, path: str = "", branch: str = "main"
) -> List[str]:
    """Обнаруживает файлы через API содержимого (для старых репо)"""
    api = f"https://api.github.com/repos/{owner}/{repo}/contents"
    if path:
        api += f"/{path.lstrip('/')}"
    api += f"?ref={urllib.parse.quote(branch)}"

    data = fetch_json(api)
    if not data:
        return []

    if isinstance(data, dict):
        data = [data]

    found = []
    config_found = []

    for item in data:
        item_type = item.get("type")
        item_path = item.get("path") or ""

        if item_type == "dir":
            found.extend(discover_github_files_contents(owner, repo, item_path, branch))
        elif item_type == "file":
            dl = item.get("download_url")
            if dl and is_probably_source_file(item_path):
                if is_config_directory(item_path):
                    config_found.append(dl)
                else:
                    found.append(dl)

    return config_found + found


def build_source_urls(cfg: Dict) -> List[str]:
    """Собирает все URL источников из репозиториев и прямых ссылок"""
    urls = []
    seen = set()

    logger.info("=== Сканирование репозиториев ===")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for repo in cfg["source_repos"]:
            future = executor.submit(discover_github_files, repo)
            futures[future] = repo

        for future in as_completed(futures):
            repo = futures[future]
            try:
                discovered = future.result()
                logger.info(f"SCAN {repo} — найдено {len(discovered)} файлов")
                for u in discovered:
                    if u not in seen:
                        seen.add(u)
                        urls.append(u)
            except Exception as e:
                logger.error(f"ERR  discover {repo} — {e}")

    # Добавляем прямые ссылки
    for u in cfg["direct_urls"]:
        if u not in seen:
            seen.add(u)
            urls.append(u)

    logger.info(f"НАЙДЕНО {len(urls)} источников")
    return urls


# ==================== Парсинг VLESS ====================

def decode_if_needed(text: str) -> str:
    """Декодирует base64 если нужно"""
    head = text[:1200].lower()
    if "vless://" in head:
        return text

    cleaned = "".join(text.split())
    if len(cleaned) < 32:
        return text

    try:
        cleaned += "=" * (-len(cleaned) % 4)
        decoded = base64.b64decode(cleaned).decode("utf-8", errors="ignore")
        if "vless://" in decoded.lower():
            return decoded
    except Exception:
        pass

    return text


def clean_node(url: str) -> str:
    """Очищает URL от лишних символов"""
    return url.strip().rstrip("),.;]}'\"")


def safe_name(raw: str, idx: int) -> str:
    """Создает безопасное имя для прокси"""
    raw = urllib.parse.unquote(raw or "")
    raw = raw.encode("ascii", errors="ignore").decode("ascii")
    raw = re.sub(r"[^a-zA-Z0-9 \-_.(),]+", "", raw).strip()
    return raw[:60] if len(raw) >= 2 else f"proxy-{idx}"


def parse_vless(url: str, idx: int) -> Optional[Dict]:
    """Парсит VLESS URL в объект конфига"""
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme.lower() != "vless" or not p.hostname or not p.port:
            return None

        params = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        sec = (params.get("security", ["none"])[0] or "none").lower()

        # Только TLS / Reality
        if sec not in ("tls", "reality"):
            return None

        proxy = {
            "name": safe_name(p.fragment, idx),
            "type": "vless",
            "server": p.hostname,
            "port": int(p.port),
            "uuid": urllib.parse.unquote(p.username or ""),
            "tls": True,
            "udp": True,
            "skip-cert-verify": True,
        }

        net = (params.get("type", ["tcp"])[0] or "tcp").lower()
        if net != "tcp":
            proxy["network"] = net

        flow = params.get("flow", [""])[0]
        if flow:
            proxy["flow"] = flow

        sni = params.get("sni", [""])[0]
        if sni:
            proxy["servername"] = sni

        fp = params.get("fp", [""])[0]
        if fp:
            proxy["client-fingerprint"] = fp

        packet_encoding = (
            params.get("packet-encoding", [""])[0]
            or params.get("packetEncoding", [""])[0]
        )
        if packet_encoding:
            proxy["packet-encoding"] = packet_encoding

        if net == "ws":
            ws_opts = {}
            path = params.get("path", [""])[0]
            host = params.get("host", [""])[0]
            if path:
                ws_opts["path"] = urllib.parse.unquote(path)
            if host:
                ws_opts["headers"] = {"Host": host}
            if ws_opts:
                proxy["ws-opts"] = ws_opts

        elif net == "grpc":
            grpc_name = urllib.parse.unquote(params.get("serviceName", [""])[0])
            if grpc_name:
                proxy["grpc-opts"] = {"grpc-service-name": grpc_name}

        if sec == "reality":
            proxy["reality-opts"] = {
                "public-key": params.get("pbk", [""])[0],
                "short-id": params.get("sid", [""])[0],
            }

        return proxy
    except Exception:
        return None


def parse_node(url: str, idx: int) -> Optional[Dict]:
    """Парсит VLESS узел"""
    if url.startswith("vless://"):
        return parse_vless(url, idx)
    return None


# ==================== Генерация YAML ====================

def yaml_scalar(value) -> str:
    """Преобразует значение в YAML скаляр"""
    return json.dumps(value, ensure_ascii=False)


def make_clash(proxies: List[Dict]) -> str:
    """Генерирует Clash конфигурацию"""
    names = [p["name"] for p in proxies]
    top = names[:150]

    out = [
        "mixed-port: 7890",
        "allow-lan: false",
        "mode: global",
        "log-level: info",
        "external-controller: 127.0.0.1:9090",
        "",
        "dns:",
        "  enable: true",
        "  nameserver:",
        "    - 8.8.8.8",
        "    - 1.1.1.1",
        "",
        "proxies:",
    ]

    for p in proxies:
        out.append(f"  - name: {yaml_scalar(p['name'])}")
        out.append("    type: vless")
        out.append(f"    server: {yaml_scalar(p['server'])}")
        out.append(f"    port: {int(p['port'])}")
        out.append(f"    uuid: {yaml_scalar(p['uuid'])}")
        out.append(f"    tls: {str(bool(p.get('tls', True))).lower()}")
        out.append(f"    udp: {str(bool(p.get('udp', True))).lower()}")
        out.append(f"    skip-cert-verify: {str(bool(p.get('skip-cert-verify', True))).lower()}")

        if p.get("flow"):
            out.append(f"    flow: {yaml_scalar(p['flow'])}")
        if p.get("network"):
            out.append(f"    network: {yaml_scalar(p['network'])}")
        if p.get("client-fingerprint"):
            out.append(f"    client-fingerprint: {yaml_scalar(p['client-fingerprint'])}")
        if p.get("servername"):
            out.append(f"    servername: {yaml_scalar(p['servername'])}")
        if p.get("packet-encoding"):
            out.append(f"    packet-encoding: {yaml_scalar(p['packet-encoding'])}")

        if p.get("reality-opts"):
            ro = p["reality-opts"]
            out.append("    reality-opts:")
            out.append(f"      public-key: {yaml_scalar(ro.get('public-key', ''))}")
            out.append(f"      short-id: {yaml_scalar(ro.get('short-id', ''))}")

        if p.get("ws-opts"):
            wo = p["ws-opts"]
            out.append("    ws-opts:")
            if wo.get("path"):
                out.append(f"      path: {yaml_scalar(wo['path'])}")
            if wo.get("headers"):
                out.append("      headers:")
                for k, v in wo["headers"].items():
                    out.append(f"        {k}: {yaml_scalar(v)}")

        if p.get("grpc-opts"):
            out.append("    grpc-opts:")
            out.append(
                f"      grpc-service-name: {yaml_scalar(p['grpc-opts'].get('grpc-service-name', ''))}"
            )

    out += [
        "",
        "proxy-groups:",
        f"  - name: {yaml_scalar('Auto')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:",
    ] + [f"      - {yaml_scalar(n)}" for n in top] + [
        "",
        f"  - name: {yaml_scalar('PROXY')}",
        "    type: select",
        "    proxies:",
        f"      - {yaml_scalar('Auto')}",
    ] + [f"      - {yaml_scalar(n)}" for n in top] + [
        "",
        "rules:",
        "  - MATCH,Auto",
    ]

    return "\n".join(out)


# ==================== Отчеты ====================

def generate_text_report(
    source_urls: List[str],
    ordered_nodes: List[str],
    proxies: List[Dict],
    tested_count: int = 0,
    working_count: int = 0,
    avg_ping: float = 0.0,
) -> str:
    """Генерирует красивый текстовый отчет"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = f"""╔════════════════════════════════════════════════════╗
║          ОТЧЕТ СБОРА ПРОКСИ КОНФИГУРАЦИЙ         ║
╚════════════════════════════════════════════════════╝

Время: {timestamp}
Кэш свежий: {not should_refresh_cache()}

📊 СТАТИСТИКА СБОРА:
  └─ Источников найдено: {len(source_urls)}
  └─ VLESS узлов собрано: {len(ordered_nodes)}
  └─ Успешно распарсено для Clash: {len(proxies)}
  └─ Процент успеха парсинга: {len(proxies)/max(1, len(ordered_nodes))*100:.1f}%
"""

    if tested_count > 0:
        success_rate = (working_count / tested_count) * 100
        report += f"""
🧪 ТЕСТИРОВАНИЕ ПИНГОМ:
  └─ Протестировано: {tested_count}
  └─ Рабочих: {working_count}
  └─ Успешность: {success_rate:.1f}%
  └─ Средний пинг: {avg_ping:.0f}мс
"""

    report += f"""
📁 ВЫХОДНЫЕ ФАЙЛЫ:
  └─ sub.txt: {len(ordered_nodes[:DEFAULT_CONFIG['sub_limit']])} узлов (base64)
  └─ clash.yaml: {len(proxies)} узлов (YAML конфиг)

ℹ️  Логи сохранены в: {LOG_FILE}
"""

    return report


def generate_json_report(
    source_urls: List[str],
    ordered_nodes: List[str],
    proxies: List[Dict],
    tested_count: int = 0,
    working_count: int = 0,
    avg_ping: float = 0.0,
) -> Dict:
    """Генерирует JSON отчет для машинной обработки"""
    return {
        "timestamp": datetime.now().isoformat(),
        "statistics": {
            "sources_found": len(source_urls),
            "vless_nodes_collected": len(ordered_nodes),
            "vless_nodes_parsed": len(proxies),
            "parsing_success_rate": round(len(proxies)/max(1, len(ordered_nodes))*100, 1),
        },
        "testing": {
            "enabled": tested_count > 0,
            "sample_tested": tested_count,
            "working_proxies": working_count,
            "success_rate": round((working_count / tested_count) * 100, 1) if tested_count > 0 else 0,
            "average_ping_ms": round(avg_ping, 1) if tested_count > 0 else 0,
        },
        "output_files": {
            "sub_txt": {
                "path": "sub.txt",
                "nodes_count": len(ordered_nodes[:DEFAULT_CONFIG['sub_limit']]),
                "format": "base64",
                "description": "For subscriptions"
            },
            "clash_yaml": {
                "path": "clash.yaml",
                "nodes_count": len(proxies),
                "format": "YAML",
                "description": "Clash configuration"
            }
        },
        "cache": {
            "ttl_hours": CACHE_TTL_HOURS,
            "next_refresh": (datetime.now() + timedelta(hours=CACHE_TTL_HOURS)).isoformat()
        }
    }


# ==================== Главная функция ====================

def main():
    """Основная функция сборщика прокси"""
    logger.info("=" * 60)
    logger.info("ЗАПУСК СБОРЩИКА ПРОКСИ КОНФИГУРАЦИЙ")
    logger.info("=" * 60)

    try:
        cfg = load_config()

        if not cfg["source_repos"] and not cfg["direct_urls"]:
            raise ProxyCollectorError("Нет источников в конфигурации")

        # Проверяем, нужно ли обновлять данные
        if not should_refresh_cache():
            logger.info("Кэш свежий, пропускаем обновление")
            return

        source_urls = build_source_urls(cfg)

        if not source_urls:
            raise ProxyCollectorError("Не найдено источников для загрузки")

        sub_limit = int(cfg["sub_limit"])
        clash_limit = int(cfg["clash_limit"])
        collection_target = max(sub_limit, clash_limit) + 300

        logger.info("=== Сбор VLESS узлов ===")
        ordered_nodes = []
        seen_nodes = set()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for src in source_urls:
                if len(ordered_nodes) >= collection_target:
                    break
                future = executor.submit(fetch_text, src)
                futures[future] = src

            for future in as_completed(futures):
                if len(ordered_nodes) >= collection_target:
                    break

                src = futures[future]
                try:
                    raw = future.result()
                    if not raw:
                        continue

                    text = decode_if_needed(raw)
                    found = [clean_node(m) for m in NODE_RE.findall(text)]
                    found = [n for n in found if n.startswith("vless://")]

                    if found:
                        logger.info(f"OK  {src.split('/')[-1]} — {len(found)} vless")
                    else:
                        logger.info(f"OK  {src.split('/')[-1]} — 0 vless")

                    for node in found:
                        if node not in seen_nodes:
                            seen_nodes.add(node)
                            ordered_nodes.append(node)

                        if len(ordered_nodes) >= collection_target:
                            break

                except Exception as e:
                    logger.error(f"Ошибка при обработке {src}: {e}")

        if not ordered_nodes:
            raise ProxyCollectorError("Не собрано ни одного VLESS узла")

        logger.info(f"Всего уникальных VLESS: {len(ordered_nodes)}")

        # ========== Тестирование п��окси ==========
        tested_count = 0
        working_count = 0
        avg_ping = 0.0

        if cfg.get("test_proxies", TEST_PROXIES):
            logger.info("=== Тестирование прокси ===")
            test_sample = ordered_nodes[:TEST_SAMPLE_SIZE] if TEST_SAMPLE_SIZE > 0 else ordered_nodes

            pings = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(test_proxy_ping, node): node for node in test_sample}

                for future in as_completed(futures):
                    try:
                        success, ping = future.result()
                        tested_count += 1
                        if success:
                            working_count += 1
                            pings.append(ping)
                    except Exception as e:
                        logger.debug(f"Ошибка при тестировании: {e}")

            if pings:
                avg_ping = sum(pings) / len(pings)
                logger.info(f"Протестировано: {tested_count}, рабочих: {working_count}, средний пинг: {avg_ping:.0f}мс")

        # ========== Сохранение sub.txt ==========
        sub_nodes = ordered_nodes[:sub_limit]
        encoded = base64.b64encode("\n".join(sub_nodes).encode("utf-8")).decode("ascii")
        with open("sub.txt", "w", encoding="utf-8") as f:
            f.write(encoded)
        logger.info(f"sub.txt записан ({len(sub_nodes)} узлов)")

        # ========== Сохранение clash.yaml ==========
        proxies = []
        seen_names = set()

        logger.info("=== Парсинг VLESS для Clash ===")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(parse_node, url, idx): (url, idx) for idx, url in enumerate(ordered_nodes)}

            for future in as_completed(futures):
                if len(proxies) >= clash_limit:
                    break

                url, idx = futures[future]
                try:
                    p = future.result()
                    if not p:
                        continue

                    base = p["name"]
                    name = base
                    c = 1
                    while name in seen_names:
                        name = f"{base}-{c}"
                        c += 1

                    p["name"] = name
                    seen_names.add(name)
                    proxies.append(p)

                except Exception as e:
                    logger.debug(f"Ошибка при парсинге {url}: {e}")

        if not proxies:
            raise ProxyCollectorError("Не распарсено ни одного прокси для Clash")

        with open("clash.yaml", "w", encoding="utf-8") as f:
            f.write(make_clash(proxies))

        logger.info(f"clash.yaml записан ({len(proxies)} узлов)")

        # ========== Сохранение отчетов ==========
        text_report = generate_text_report(source_urls, ordered_nodes, proxies, tested_count, working_count, avg_ping)
        json_report = generate_json_report(source_urls, ordered_nodes, proxies, tested_count, working_count, avg_ping)

        # Сохраняем основные отчеты
        REPORT_FILE.write_text(text_report, encoding="utf-8")
        REPORT_JSON_FILE.write_text(json.dumps(json_report, ensure_ascii=False, indent=2), encoding="utf-8")

        # Сохраняем с датой в папку reports
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dated_report_txt = REPORTS_DIR / f"report_{timestamp}.txt"
        dated_report_json = REPORTS_DIR / f"report_{timestamp}.json"

        dated_report_txt.write_text(text_report, encoding="utf-8")
        dated_report_json.write_text(json.dumps(json_report, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(f"Отчеты сохранены:")
        logger.info(f"  - {REPORT_FILE}")
        logger.info(f"  - {REPORT_JSON_FILE}")
        logger.info(f"  - {dated_report_txt}")
        logger.info(f"  - {dated_report_json}")

        # ========== Обновление кэша ==========
        update_cache_timestamp()

        print("\n" + text_report)
        logger.info("=" * 60)
        logger.info("СБОРКА ЗАВЕРШЕНА УСПЕШНО")
        logger.info("=" * 60)

    except ProxyCollectorError as e:
        logger.critical(f"ОШИБКА СБОРЩИКА: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
