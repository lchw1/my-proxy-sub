"""
VLESS collector with async fetching + TLS handshake check.

Requirements:
    pip install requests aiohttp

Optional env vars:
    GITHUB_TOKEN  — personal access token
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

# ---------------------------------------------------------------------------
CONFIG_FILE = Path("sources.json")

DEFAULT_CONFIG = {
    "source_repos": [],
    "direct_urls": [
        "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",
        "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-vless-configs-russia/main/githubmirror/clean/vless.txt",
        "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
        "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/all_extracted_configs.txt",
        "https://raw.githubusercontent.com/ShatakVPN/ConfigForge-V2Ray/main/configs/vless.txt",
        "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt",
        "https://raw.githubusercontent.com/4n0nymou3/multi-proxy-config-fetcher/main/configs/proxy_configs.txt",
    ],
    "sub_limit": 550,
    "clash_limit": 500,
    "latency_limit_ms": 200,
    "test_workers": 100,
    "test_timeout_ms": 2000,
    "github_token": "",
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
# Node helpers
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
# Async fetch всех источников параллельно
# ---------------------------------------------------------------------------

async def fetch_one(session: aiohttp.ClientSession, url: str) -> str:
    label = url.split("/")[-1]
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                text = await r.text(encoding="utf-8", errors="ignore")
                return text
            print(f"SKIP {label} — HTTP {r.status}")
    except asyncio.TimeoutError:
        print(f"TIMEOUT {label}")
    except Exception as e:
        print(f"ERR  {label} — {e}")
    return ""


async def fetch_all_sources(urls: list, headers: dict) -> list:
    """Скачивает все источники параллельно, возвращает список уникальных нод."""
    print(f"Скачиваем {len(urls)} источников параллельно...")

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [fetch_one(session, url) for url in urls]
        results = await asyncio.gather(*tasks)

    nodes = []
    seen: set = set()

    for i, text in enumerate(results):
        if not text:
            continue
        decoded = decode_if_needed(text)
        found = [clean_node(m) for m in NODE_RE.findall(decoded) if m.startswith("vless://")]
        label = urls[i].split("/")[-1]
        print(f"OK  {label} — {len(found)} vless")
        for node in found:
            if node not in seen:
                seen.add(node)
                nodes.append(node)

    print(f"\nВсего уникальных VLESS до фильтрации: {len(nodes)}")
    return nodes


# ---------------------------------------------------------------------------
# Async TLS handshake check
# ---------------------------------------------------------------------------

async def tls_latency_ms(host: str, port: int, sni: str, timeout_s: float):
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Чистим SNI — только ASCII, иначе падает с UnicodeError
    try:
        sni_clean = sni.encode("idna").decode("ascii")
    except Exception:
        try:
            sni_clean = host.encode("idna").decode("ascii")
        except Exception:
            return None  # кривой хост — пропускаем

    t0 = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni_clean),
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


async def _tls_worker(queue: asyncio.Queue, results: list, timeout_s: float, limit_ms: float):
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


async def tls_test_nodes(nodes: list, limit_ms: int, workers: int, timeout_ms: int) -> list:
    """
    TLS handshake тест всех нод параллельно.
    Возвращает ноды прошедшие тест, отсортированные по задержке.
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
        return nodes

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
        asyncio.create_task(_tls_worker(queue, results, timeout_s, float(limit_ms)))
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


def parse_vless(url: str, idx: int):
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


def make_clash(proxies: list) -> str:
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

async def run(cfg: dict):
    headers = get_headers(cfg)

    # Собираем все URL источников
    source_urls = list(cfg["direct_urls"])
    print(f"Источников: {len(source_urls)}")

    if not source_urls:
        print("CRITICAL: no sources configured.")
        sys.exit(1)
        
# Берём не более 1500 нод на тест — больше не нужно
max_for_test = 1500
if len(ordered_nodes) > max_for_test:
    print(f"Обрезаем до {max_for_test} нод для TLS-теста")
    ordered_nodes = ordered_nodes[:max_for_test]
    
    # 1. Скачиваем все источники параллельно
    print("\n=== Сбор VLESS узлов ===")
    ordered_nodes = await fetch_all_sources(source_urls, headers)

    if not ordered_nodes:
        print("CRITICAL: 0 nodes collected!")
        sys.exit(1)

    # 2. TLS-test
    passed_nodes = await tls_test_nodes(
        ordered_nodes,
        limit_ms=cfg["latency_limit_ms"],
        workers=cfg["test_workers"],
        timeout_ms=cfg["test_timeout_ms"],
    )

    if not passed_nodes:
        print("WARNING: 0 нод прошли TLS-test — используем все ноды без фильтрации.")
        passed_nodes = ordered_nodes

    # 3. sub.txt
    sub_nodes = passed_nodes[:cfg["sub_limit"]]
    encoded = base64.b64encode("\n".join(sub_nodes).encode("utf-8")).decode("ascii")
    Path("sub.txt").write_text(encoded, encoding="utf-8")
    print(f"\nsub.txt записан ({len(sub_nodes)} узлов)")

    # 4. clash.yaml
    proxies: list = []
    seen_names: set = set()

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
        if len(proxies) >= cfg["clash_limit"]:
            break

    if not proxies:
        print("CRITICAL: 0 proxies for clash (нет TLS/Reality нод)!")
        sys.exit(1)

    Path("clash.yaml").write_text(make_clash(proxies), encoding="utf-8")
    print(f"clash.yaml записан ({len(proxies)} узлов)")


def main():
    cfg = load_config()
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
