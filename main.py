"""
VLESS collector with async TLS handshake check and GitHub token support.

Requirements:
    pip install requests aiohttp

Optional env vars:
    GITHUB_TOKEN  — personal access token (raises limit 60 → 5000 req/hour)

Config (sources.json) new fields:
    github_token      — alternative to env var
    latency_limit_ms  — drop nodes slower than this (default 200)
    test_workers      — parallel TCP testers (default 100)
    test_timeout_ms   — TCP connect timeout (default 2000)
"""

import asyncio
import base64
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import aiohttp
import requests

# ---------------------------------------------------------------------------
CONFIG_FILE = Path("sources.json")

DEFAULT_CONFIG = {
    # --- источники ---
    "source_repos": [
        # активные коллекции 2024-2025
        "https://github.com/mahdibland/V2RayAggregator",
        "https://github.com/soroushmirzaei/telegram-configs-collector",
        "https://github.com/Epodonios/v2ray-configs",
        "https://github.com/yebekhe/TelegramV2rayCollector",
        "https://github.com/barry-far/V2ray-Configs",
        "https://github.com/SoliSpirit/v2ray-configs",
        "https://github.com/mfuu/v2ray",
        "https://github.com/resasanian/Mirza",
    ],
    "direct_urls": [],
    # --- лимиты вывода ---
    "sub_limit": 550,
    "clash_limit": 500,
    # --- speed-test ---
    "latency_limit_ms": 200,   # выкидывать ноды медленнее этого порога
    "test_workers": 100,        # параллельных TCP-соединений
    "test_timeout_ms": 2000,    # таймаут одного TCP connect
    # --- GitHub API ---
    "github_token": "",         # или задайте GITHUB_TOKEN в env
}

ALLOWED_EXTS = {".txt", ".sub", ".base64", ".b64", ".list", ".yaml", ".yml"}
SKIP_NAME_PARTS = {
    "readme", "license", "changelog", "requirements", "setup",
    "example", "sample", "test", "demo", "package-lock", "pyproject",
    "makefile", ".github", "workflow",
}
NODE_RE = re.compile(r"vless://[^\s\r\n'\"<>]+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = DEFAULT_CONFIG.copy()
                for key in DEFAULT_CONFIG:
                    if key in data:
                        cfg[key] = data[key]
                cfg["source_repos"] = [s.strip() for s in cfg["source_repos"] if str(s).strip()]
                cfg["direct_urls"] = [s.strip() for s in cfg["direct_urls"] if str(s).strip()]
                for int_key in ("sub_limit", "clash_limit", "latency_limit_ms",
                                "test_workers", "test_timeout_ms"):
                    cfg[int_key] = int(cfg[int_key])
                return cfg
        except Exception:
            pass

    CONFIG_FILE.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return DEFAULT_CONFIG.copy()


def get_headers(cfg: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or cfg.get("github_token", "")
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ---------------------------------------------------------------------------
# HTTP helpers (sync, для GitHub API и скачивания файлов)
# ---------------------------------------------------------------------------

def fetch_text(url: str, headers: dict, timeout: int = 25) -> str:
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.text
        print(f"SKIP {url} — HTTP {r.status_code}")
    except Exception as e:
        print(f"ERR  {url} — {e}")
    return ""


def fetch_json(url: str, headers: dict, timeout: int = 25):
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        print(f"SKIP {url} — HTTP {r.status_code}")
    except Exception as e:
        print(f"ERR  {url} — {e}")
    return None


# ---------------------------------------------------------------------------
# GitHub discovery
# ---------------------------------------------------------------------------

def github_owner_repo(repo_url: str):
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$",
        repo_url.strip(),
    )
    if not m:
        return None, None
    return m.group(1), m.group(2)


def is_probably_source_file(path: str) -> bool:
    lower = path.lower()
    name = Path(lower).name
    ext = Path(name).suffix
    if ext not in ALLOWED_EXTS:
        return False
    if any(part in lower for part in SKIP_NAME_PARTS):
        return False
    return True


def raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    safe_path = urllib.parse.quote(path, safe="/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{safe_path}"


def discover_github_files(repo_url: str, headers: dict) -> list[str]:
    owner, repo = github_owner_repo(repo_url)
    if not owner or not repo:
        return []

    info = fetch_json(f"https://api.github.com/repos/{owner}/{repo}", headers)
    if not isinstance(info, dict):
        return []

    branch = info.get("default_branch") or "main"
    tree = fetch_json(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers,
    )

    if isinstance(tree, dict) and isinstance(tree.get("tree"), list):
        urls = []
        for item in tree["tree"]:
            if item.get("type") != "blob":
                continue
            path = item.get("path") or ""
            if is_probably_source_file(path):
                urls.append(raw_url(owner, repo, branch, path))
        return urls

    # fallback
    return _discover_contents(owner, repo, "", branch, headers)


def _discover_contents(
    owner: str, repo: str, path: str, branch: str, headers: dict
) -> list[str]:
    api = f"https://api.github.com/repos/{owner}/{repo}/contents"
    if path:
        api += f"/{path.lstrip('/')}"
    api += f"?ref={urllib.parse.quote(branch)}"

    data = fetch_json(api, headers)
    if not data:
        return []
    if isinstance(data, dict):
        data = [data]

    found = []
    for item in data:
        if item.get("type") == "dir":
            found.extend(_discover_contents(owner, repo, item.get("path", ""), branch, headers))
        elif item.get("type") == "file":
            p = item.get("path") or ""
            dl = item.get("download_url")
            if dl and is_probably_source_file(p):
                found.append(dl)
    return found


# ---------------------------------------------------------------------------
# Node extraction
# ---------------------------------------------------------------------------

def decode_if_needed(text: str) -> str:
    if "vless://" in text[:1200].lower():
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
    return url.strip().rstrip("),.;]}'\"")


# ---------------------------------------------------------------------------
# Async TLS handshake check
# ---------------------------------------------------------------------------

async def tls_latency_ms(host: str, port: int, sni: str, timeout_s: float) -> float | None:
    """
    Выполняет полный TLS handshake и возвращает время в мс.
    Если TLS не прошёл (нет сертификата, таймаут, отказ) — возвращает None.
    Это намного надёжнее чем просто TCP connect:
    - сервер должен реально отвечать на TLS
    - мусорные/мёртвые ноды отсеиваются
    """
    import ssl
    ctx = ssl.create_default_context()
    # Не проверяем цепочку сертификатов — у VPN нод часто self-signed
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    t0 = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni or host),
            timeout=timeout_s,
        )
        latency = (time.monotonic() - t0) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return latency
    except Exception:
        return None


async def _test_worker(
    queue: asyncio.Queue,
    results: list,
    timeout_s: float,
    limit_ms: float,
):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        node_url, host, port, sni = item
        lat = await tls_latency_ms(host, port, sni, timeout_s)
        if lat is not None and lat <= limit_ms:
            results.append((node_url, lat))
        queue.task_done()


async def speed_test_nodes(
    nodes: list[str],
    limit_ms: int,
    workers: int,
    timeout_ms: int,
) -> list[str]:
    """
    Асинхронный TLS handshake тест всех нод.
    Возвращает список прошедших фильтр нод, отсортированных по задержке.
    TLS надёжнее TCP — сервер должен реально отвечать на шифрование.
    """
    parsed = []
    for url in nodes:
        try:
            p = urllib.parse.urlsplit(url)
            if p.hostname and p.port:
                params = urllib.parse.parse_qs(p.query, keep_blank_values=True)
                sni = params.get("sni", [""])[0] or p.hostname
                parsed.append((url, p.hostname, int(p.port), sni))
        except Exception:
            pass

    if not parsed:
        return nodes  # нечего тестировать — вернуть как есть

    print(f"\n=== TLS-test: {len(parsed)} нод, порог {limit_ms} ms, "
          f"{workers} параллельных соединений ===")

    queue: asyncio.Queue = asyncio.Queue()
    results: list = []
    timeout_s = timeout_ms / 1000.0

    for item in parsed:
        await queue.put(item)
    for _ in range(workers):
        await queue.put(None)

    tasks = [
        asyncio.create_task(
            _test_worker(queue, results, timeout_s, float(limit_ms))
        )
        for _ in range(workers)
    ]
    await queue.join()
    await asyncio.gather(*tasks)

    results.sort(key=lambda x: x[1])
    passed = [url for url, _ in results]

    print(f"Прошло TLS-test: {len(passed)} / {len(parsed)} нод")
    if results:
        lats = [lat for _, lat in results]
        print(
            f"Задержки: min={lats[0]:.0f}ms  "
            f"med={lats[len(lats)//2]:.0f}ms  "
            f"max={lats[-1]:.0f}ms"
        )
    return passed


# ---------------------------------------------------------------------------
# VLESS parser → Clash proxy dict
# ---------------------------------------------------------------------------

def safe_name(raw: str, idx: int) -> str:
    raw = urllib.parse.unquote(raw or "")
    raw = raw.encode("ascii", errors="ignore").decode("ascii")
    raw = re.sub(r"[^a-zA-Z0-9 \-_.(),]+", "", raw).strip()
    return raw[:60] if len(raw) >= 2 else f"proxy-{idx}"


def parse_vless(url: str, idx: int) -> dict | None:
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme.lower() != "vless" or not p.hostname or not p.port:
            return None

        params = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        sec = (params.get("security", ["none"])[0] or "none").lower()

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

        if flow := params.get("flow", [""])[0]:
            proxy["flow"] = flow
        if sni := params.get("sni", [""])[0]:
            proxy["servername"] = sni
        if fp := params.get("fp", [""])[0]:
            proxy["client-fingerprint"] = fp

        pe = params.get("packet-encoding", [""])[0] or params.get("packetEncoding", [""])[0]
        if pe:
            proxy["packet-encoding"] = pe

        if net == "ws":
            ws_opts: dict = {}
            if path := urllib.parse.unquote(params.get("path", [""])[0]):
                ws_opts["path"] = path
            if host := params.get("host", [""])[0]:
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


# ---------------------------------------------------------------------------
# Clash YAML builder
# ---------------------------------------------------------------------------

def _qs(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def make_clash(proxies: list[dict]) -> str:
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
        out += [
            f"  - name: {_qs(p['name'])}",
            "    type: vless",
            f"    server: {_qs(p['server'])}",
            f"    port: {int(p['port'])}",
            f"    uuid: {_qs(p['uuid'])}",
            f"    tls: {str(bool(p.get('tls', True))).lower()}",
            f"    udp: {str(bool(p.get('udp', True))).lower()}",
            f"    skip-cert-verify: {str(bool(p.get('skip-cert-verify', True))).lower()}",
        ]
        for key in ("flow", "network", "client-fingerprint", "servername", "packet-encoding"):
            if p.get(key):
                out.append(f"    {key}: {_qs(p[key])}")

        if ro := p.get("reality-opts"):
            out += [
                "    reality-opts:",
                f"      public-key: {_qs(ro.get('public-key', ''))}",
                f"      short-id: {_qs(ro.get('short-id', ''))}",
            ]
        if wo := p.get("ws-opts"):
            out.append("    ws-opts:")
            if wo.get("path"):
                out.append(f"      path: {_qs(wo['path'])}")
            if wo.get("headers"):
                out.append("      headers:")
                for k, v in wo["headers"].items():
                    out.append(f"        {k}: {_qs(v)}")
        if go := p.get("grpc-opts"):
            out += [
                "    grpc-opts:",
                f"      grpc-service-name: {_qs(go.get('grpc-service-name', ''))}",
            ]

    out += [
        "",
        "proxy-groups:",
        f"  - name: {_qs('Auto')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:",
    ] + [f"      - {_qs(n)}" for n in top] + [
        "",
        f"  - name: {_qs('PROXY')}",
        "    type: select",
        "    proxies:",
        f"      - {_qs('Auto')}",
    ] + [f"      - {_qs(n)}" for n in top] + [
        "",
        "rules:",
        "  - MATCH,Auto",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg = load_config()
    headers = get_headers(cfg)

    if not cfg["source_repos"] and not cfg["direct_urls"]:
        print("CRITICAL: no sources configured.")
        sys.exit(1)

    # 1. Обход репозиториев
    print("=== Сбор ссылок на источники ===")
    source_urls: list[str] = []
    seen_src: set[str] = set()

    for repo in cfg["source_repos"]:
        print(f"SCAN {repo}")
        try:
            for u in discover_github_files(repo, headers):
                if u not in seen_src:
                    seen_src.add(u)
                    source_urls.append(u)
        except Exception as e:
            print(f"ERR  discover {repo} — {e}")

    for u in cfg["direct_urls"]:
        if u not in seen_src:
            seen_src.add(u)
            source_urls.append(u)

    print(f"FOUND SOURCES: {len(source_urls)}")

    sub_limit = cfg["sub_limit"]
    clash_limit = cfg["clash_limit"]
    collection_target = max(sub_limit, clash_limit) + 500

    # 2. Сбор VLESS-нод
    print("\n=== Сбор VLESS узлов ===")
    ordered_nodes: list[str] = []
    seen_nodes: set[str] = set()

    for src in source_urls:
        if len(ordered_nodes) >= collection_target:
            break
        raw = fetch_text(src, headers)
        if not raw:
            continue
        text = decode_if_needed(raw)
        found = [clean_node(m) for m in NODE_RE.findall(text) if m.startswith("vless://")]
        label = src.split("/")[-1]
        print(f"OK  {label} — {len(found)} vless")
        for node in found:
            if node not in seen_nodes:
                seen_nodes.add(node)
                ordered_nodes.append(node)
            if len(ordered_nodes) >= collection_target:
                break

    if not ordered_nodes:
        print("CRITICAL: 0 nodes collected!")
        sys.exit(1)

    print(f"\nВсего уникальных VLESS до фильтрации: {len(ordered_nodes)}")

    # 3. Async TLS-test
    passed_nodes = asyncio.run(
        speed_test_nodes(
            ordered_nodes,
            limit_ms=cfg["latency_limit_ms"],
            workers=cfg["test_workers"],
            timeout_ms=cfg["test_timeout_ms"],
        )
    )

    if not passed_nodes:
        print("WARNING: 0 нод прошли TLS-test — используем все ноды без фильтрации.")
        passed_nodes = ordered_nodes

    # 4. sub.txt
    sub_nodes = passed_nodes[:sub_limit]
    encoded = base64.b64encode("\n".join(sub_nodes).encode("utf-8")).decode("ascii")
    Path("sub.txt").write_text(encoded, encoding="utf-8")
    print(f"\nsub.txt записан ({len(sub_nodes)} узлов)")

    # 5. clash.yaml
    proxies: list[dict] = []
    seen_names: set[str] = set()

    for idx, url in enumerate(passed_nodes):
        p = parse_vless(url, idx)
        if not p:
            continue
        base = p["name"]
        name, c = base, 1
        while name in seen_names:
            name = f"{base}-{c}"
            c += 1
        p["name"] = name
        seen_names.add(name)
        proxies.append(p)
        if len(proxies) >= clash_limit:
            break

    if not proxies:
        print("CRITICAL: 0 proxies for clash (нет TLS/Reality нод)!")
        sys.exit(1)

    Path("clash.yaml").write_text(make_clash(proxies), encoding="utf-8")
    print(f"clash.yaml записан ({len(proxies)} узлов)")


if __name__ == "__main__":
    main()
