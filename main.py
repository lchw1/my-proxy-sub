"""
VLESS collector — параллельный сбор + TLS-тест.
Приоритет: Reality и WS/gRPC ноды — они лучше обходят блокировки РКН.

Requirements: pip install aiohttp
"""

import asyncio
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
from pathlib import Path

import aiohttp

# ---------------------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------------------

CONFIG_FILE = Path("sources.json")

DEFAULT_CONFIG = {
    "direct_urls": [
        "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",
        "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt",
        "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
        "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/githubmirror/clean/vless.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-vless-configs-russia/main/githubmirror/clean/vless.txt",
        "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/all_extracted_configs.txt",
        "https://raw.githubusercontent.com/4n0nymou3/multi-proxy-config-fetcher/main/configs/proxy_configs.txt",
        "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt",
    ],
    # Лимиты вывода
    "sub_limit": 500,
    "clash_limit": 450,
    # Максимум нод на TLS-тест (больше не нужно — тормозит)
    "max_test_nodes": 1500,
    # TLS-тест параметры
    "latency_limit_ms": 2000,
    "test_workers": 150,
    "test_timeout_ms": 3000,
}

NODE_RE = re.compile(r"vless://[^\s\r\n'\"<>]+", re.IGNORECASE)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = DEFAULT_CONFIG.copy()
                for key in DEFAULT_CONFIG:
                    if key in data:
                        cfg[key] = data[key]
                cfg["direct_urls"] = [
                    s.strip() for s in cfg["direct_urls"] if str(s).strip()
                ]
                for k in ("sub_limit", "clash_limit", "max_test_nodes",
                          "latency_limit_ms", "test_workers", "test_timeout_ms"):
                    cfg[k] = int(cfg[k])
                return cfg
        except Exception as e:
            print(f"WARN: ошибка чтения sources.json — {e}, используем дефолт")

    CONFIG_FILE.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return DEFAULT_CONFIG.copy()


# ---------------------------------------------------------------------------
# Параллельное скачивание источников
# ---------------------------------------------------------------------------

async def fetch_one(session: aiohttp.ClientSession, url: str) -> tuple:
    label = url.split("/")[-1]
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(connect=10, total=30),
        ) as r:
            if r.status == 200:
                text = await r.text(encoding="utf-8", errors="ignore")
                return label, text
            print(f"SKIP {label} — HTTP {r.status}")
    except asyncio.TimeoutError:
        print(f"TIMEOUT {label}")
    except Exception as e:
        print(f"ERR  {label} — {e}")
    return label, ""


def decode_if_needed(text: str) -> str:
    if "vless://" in text[:2000].lower():
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


async def collect_nodes(urls: list, max_nodes: int) -> list:
    print(f"\n=== Сбор нод из {len(urls)} источников (параллельно) ===")

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [fetch_one(session, url) for url in urls]
        results = await asyncio.gather(*tasks)

    nodes = []
    seen: set = set()

    for label, text in results:
        if not text:
            continue
        decoded = decode_if_needed(text)
        found = [
            clean_node(m)
            for m in NODE_RE.findall(decoded)
            if m.startswith("vless://")
        ]
        print(f"OK  {label} — {len(found)} vless")
        for node in found:
            if node not in seen:
                seen.add(node)
                nodes.append(node)

    print(f"\nВсего уникальных VLESS: {len(nodes)}")

   if len(nodes) > max_nodes:
        print(f"Обрезаем до {max_nodes} для TLS-теста")
        priority = []
        rest = []
        for n in nodes:
            try:
                # Оборачиваем парсинг в try, чтобы битые IPv6 ссылки не ломали скрипт
                parsed = urllib.parse.urlsplit(n)
                q = urllib.parse.parse_qs(parsed.query)
                sec = q.get("security", [""])[0].lower()
                net = q.get("type", [""])[0].lower()
                if sec == "reality" or net in ("ws", "grpc"):
                    priority.append(n)
                else:
                    rest.append(n)
            except Exception:
                # Если ссылка кривая, просто идем к следующей
                continue
                
        nodes = (priority + rest)[:max_nodes]
        print(f"  из них Reality/WS/gRPC: {len(priority)}, остальных: {len(rest)}")

    return nodes


# ---------------------------------------------------------------------------
# TLS handshake тест
# ---------------------------------------------------------------------------

def make_ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


SSL_CTX = make_ssl_ctx()


async def tls_check(host: str, port: int, sni: str, timeout_s: float):
    """Возвращает задержку TLS handshake в мс или None если не прошёл."""
    # Очищаем SNI от unicode
    try:
        sni_clean = sni.encode("idna").decode("ascii")
    except Exception:
        try:
            sni_clean = host.encode("idna").decode("ascii")
        except Exception:
            return None

    t0 = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host, port,
                ssl=SSL_CTX,
                server_hostname=sni_clean,
            ),
            timeout=timeout_s,
        )
        lat = (time.monotonic() - t0) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return lat
    except Exception:
        return None


async def _worker(queue: asyncio.Queue, results: list, timeout_s: float, limit_ms: float):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        node_url, host, port, sni = item
        lat = await tls_check(host, port, sni, timeout_s)
        if lat is not None and lat <= limit_ms:
            results.append((node_url, lat))
        queue.task_done()


async def tls_test(nodes: list, limit_ms: int, workers: int, timeout_ms: int) -> list:
    parsed = []
    for url in nodes:
        try:
            p = urllib.parse.urlsplit(url)
            if not p.hostname or not p.port:
                continue
            q = urllib.parse.parse_qs(p.query, keep_blank_values=True)
            sni = q.get("sni", [""])[0] or p.hostname
            parsed.append((url, p.hostname, int(p.port), sni))
        except Exception:
            pass

    if not parsed:
        return nodes

    print(f"\n=== TLS-тест: {len(parsed)} нод | "
          f"порог {limit_ms}ms | {workers} воркеров ===")

    queue: asyncio.Queue = asyncio.Queue()
    results: list = []
    timeout_s = timeout_ms / 1000.0

    for item in parsed:
        await queue.put(item)
    for _ in range(workers):
        await queue.put(None)

    tasks = [
        asyncio.create_task(_worker(queue, results, timeout_s, float(limit_ms)))
        for _ in range(workers)
    ]
    await queue.join()
    await asyncio.gather(*tasks)

    # Сортируем по задержке — лучшие первые
    results.sort(key=lambda x: x[1])
    passed = [url for url, _ in results]

    print(f"Прошло: {len(passed)} / {len(parsed)}")
    if results:
        lats = [lat for _, lat in results]
        mid = lats[len(lats) // 2]
        print(f"Задержки: min={lats[0]:.0f}ms  med={mid:.0f}ms  max={lats[-1]:.0f}ms")

    return passed


# ---------------------------------------------------------------------------
# VLESS → Clash парсер
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

        q = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        sec = (q.get("security", ["none"])[0] or "none").lower()

        # Только TLS и Reality — они реально работают
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

        net = (q.get("type", ["tcp"])[0] or "tcp").lower()
        if net != "tcp":
            proxy["network"] = net

        if flow := q.get("flow", [""])[0]:
            proxy["flow"] = flow
        if sni := q.get("sni", [""])[0]:
            proxy["servername"] = sni
        if fp := q.get("fp", [""])[0]:
            proxy["client-fingerprint"] = fp

        pe = q.get("packet-encoding", [""])[0] or q.get("packetEncoding", [""])[0]
        if pe:
            proxy["packet-encoding"] = pe

        if net == "ws":
            wo: dict = {}
            if path := urllib.parse.unquote(q.get("path", [""])[0]):
                wo["path"] = path
            if host := q.get("host", [""])[0]:
                wo["headers"] = {"Host": host}
            if wo:
                proxy["ws-opts"] = wo

        elif net == "grpc":
            gn = urllib.parse.unquote(q.get("serviceName", [""])[0])
            if gn:
                proxy["grpc-opts"] = {"grpc-service-name": gn}

        if sec == "reality":
            proxy["reality-opts"] = {
                "public-key": q.get("pbk", [""])[0],
                "short-id": q.get("sid", [""])[0],
            }

        return proxy
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Clash YAML
# ---------------------------------------------------------------------------

def j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def make_clash(proxies: list) -> str:
    names = [p["name"] for p in proxies]
    top = names[:150]

    out = [
        "mixed-port: 7890",
        "allow-lan: false",
        "mode: rule",
        "log-level: info",
        "external-controller: 127.0.0.1:9090",
        "",
        "dns:",
        "  enable: true",
        "  ipv6: false",
        "  nameserver:",
        "    - 8.8.8.8",
        "    - 1.1.1.1",
        "  fallback:",
        "    - tls://8.8.8.8:853",
        "    - tls://1.1.1.1:853",
        "",
        "proxies:",
    ]

    for p in proxies:
        out += [
            f"  - name: {j(p['name'])}",
            "    type: vless",
            f"    server: {j(p['server'])}",
            f"    port: {int(p['port'])}",
            f"    uuid: {j(p['uuid'])}",
            f"    tls: {str(p.get('tls', True)).lower()}",
            f"    udp: {str(p.get('udp', True)).lower()}",
            f"    skip-cert-verify: {str(p.get('skip-cert-verify', True)).lower()}",
        ]
        for key in ("flow", "network", "client-fingerprint", "servername", "packet-encoding"):
            if p.get(key):
                out.append(f"    {key}: {j(p[key])}")

        if ro := p.get("reality-opts"):
            out += [
                "    reality-opts:",
                f"      public-key: {j(ro.get('public-key', ''))}",
                f"      short-id: {j(ro.get('short-id', ''))}",
            ]
        if wo := p.get("ws-opts"):
            out.append("    ws-opts:")
            if wo.get("path"):
                out.append(f"      path: {j(wo['path'])}")
            if wo.get("headers"):
                out.append("      headers:")
                for k, v in wo["headers"].items():
                    out.append(f"        {k}: {j(v)}")
        if go := p.get("grpc-opts"):
            out += [
                "    grpc-opts:",
                f"      grpc-service-name: {j(go.get('grpc-service-name', ''))}",
            ]

    out += [
        "",
        "proxy-groups:",
        f"  - name: {j('Auto')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:",
    ] + [f"      - {j(n)}" for n in top] + [
        "",
        f"  - name: {j('PROXY')}",
        "    type: select",
        "    proxies:",
        f"      - {j('Auto')}",
    ] + [f"      - {j(n)}" for n in top] + [
        "",
        "rules:",
        # Прямой доступ к российским ресурсам
        "  - GEOIP,RU,DIRECT",
        "  - DOMAIN-SUFFIX,ru,DIRECT",
        "  - DOMAIN-SUFFIX,рф,DIRECT",
        "  - DOMAIN-SUFFIX,gosuslugi.ru,DIRECT",
        "  - DOMAIN-SUFFIX,mos.ru,DIRECT",
        "  - DOMAIN-SUFFIX,sberbank.ru,DIRECT",
        "  - DOMAIN-SUFFIX,tinkoff.ru,DIRECT",
        "  - DOMAIN-SUFFIX,yandex.ru,DIRECT",
        "  - DOMAIN-SUFFIX,vk.com,DIRECT",
        "  - DOMAIN-SUFFIX,mail.ru,DIRECT",
        "  - GEOIP,CN,DIRECT",
        "  - MATCH,Auto",
    ]

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(cfg: dict):
    urls = cfg["direct_urls"]
    if not urls:
        print("CRITICAL: нет источников в конфиге!")
        sys.exit(1)

    # 1. Параллельный сбор
    nodes = await collect_nodes(urls, cfg["max_test_nodes"])
    if not nodes:
        print("CRITICAL: 0 нод собрано!")
        sys.exit(1)

    # 2. TLS-тест
    passed = await tls_test(
        nodes,
        limit_ms=cfg["latency_limit_ms"],
        workers=cfg["test_workers"],
        timeout_ms=cfg["test_timeout_ms"],
    )
    if not passed:
        print("WARNING: никто не прошёл TLS-тест, берём всё без фильтрации")
        passed = nodes

    # 3. sub.txt
    sub = passed[:cfg["sub_limit"]]
    encoded = base64.b64encode("\n".join(sub).encode()).decode("ascii")
    Path("sub.txt").write_text(encoded, encoding="utf-8")
    print(f"\nsub.txt — {len(sub)} нод")

    # 4. clash.yaml
    proxies: list = []
    seen_names: set = set()
    for idx, url in enumerate(passed):
        p = parse_vless(url, idx)
        if not p:
            continue
        name, c = p["name"], 1
        base = name
        while name in seen_names:
            name = f"{base}-{c}"
            c += 1
        p["name"] = name
        seen_names.add(name)
        proxies.append(p)
        if len(proxies) >= cfg["clash_limit"]:
            break

    if not proxies:
        print("CRITICAL: 0 TLS/Reality прокси для clash!")
        sys.exit(1)

    Path("clash.yaml").write_text(make_clash(proxies), encoding="utf-8")
    print(f"clash.yaml — {len(proxies)} нод")
    print("\nГотово!")


def main():
    cfg = load_config()
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
