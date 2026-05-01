"""
Сбор VLESS нод для России.
Только Reality и WS — они проходят РКН.
Источники специально отобраны под Россию.
"""

import asyncio
import base64
import re
import urllib.parse
from pathlib import Path

import aiohttp

# Источники специально для России + крупные агрегаторы
SOURCES = [
    # Специально для России
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/githubmirror/clean/vless.txt",
    "https://raw.githubusercontent.com/kort0881/vpn-vless-configs-russia/main/githubmirror/clean/vless.txt",
    # Крупные агрегаторы с Reality нодами
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/4n0nymou3/multi-proxy-config-fetcher/main/configs/proxy_configs.txt",
    "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt",
]

MAX_NODES = 2000
NODE_RE   = re.compile(r"vless://[^\s\r\n'\"<>]+", re.IGNORECASE)
HEADERS   = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}


def get_sec_net(url: str):
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        sec = q.get("security", [""])[0].lower()
        net = q.get("type",     [""])[0].lower()
        return sec, net
    except Exception:
        return "", ""


def node_priority(url: str) -> int:
    sec, net = get_sec_net(url)
    if sec == "reality":           return 0  # лучший обход РКН
    if net in ("ws", "grpc"):      return 1  # прячется под веб
    if sec == "tls":               return 2  # обычный TLS
    return 3                                  # остальное


def is_useful(url: str) -> bool:
    """Фильтруем ноды без TLS/Reality — они бесполезны в России."""
    sec, _ = get_sec_net(url)
    return sec in ("tls", "reality")


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


async def fetch_one(session: aiohttp.ClientSession, url: str) -> tuple:
    label = url.split("/")[-1]
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(connect=8, total=25)) as r:
            if r.status == 200:
                return label, await r.text(encoding="utf-8", errors="ignore")
            print(f"SKIP {label} — HTTP {r.status}")
    except asyncio.TimeoutError:
        print(f"TIMEOUT {label}")
    except Exception as e:
        print(f"ERR  {label} — {e}")
    return label, ""


async def main():
    print(f"Качаем {len(SOURCES)} источников параллельно...")

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        results = await asyncio.gather(*[fetch_one(session, u) for u in SOURCES])

    nodes = []
    seen: set = set()

    for label, text in results:
        if not text:
            continue
        decoded = decode_if_needed(text)
        found = [
            u.strip().rstrip("),.;]}'\"")
            for u in NODE_RE.findall(decoded)
            if u.startswith("vless://")
        ]
        # Сразу фильтруем — только TLS/Reality
        found = [n for n in found if is_useful(n)]
        print(f"  {label}: {len(found)} vless (TLS/Reality)")
        for node in found:
            if node not in seen:
                seen.add(node)
                nodes.append(node)

    total = len(nodes)
    print(f"\nВсего TLS/Reality нод: {total}")

    # Сортируем: Reality первыми
    nodes.sort(key=node_priority)

    r = sum(1 for n in nodes if node_priority(n) == 0)
    w = sum(1 for n in nodes if node_priority(n) == 1)
    t = sum(1 for n in nodes if node_priority(n) == 2)
    print(f"  Reality: {r}  WS/gRPC: {w}  TLS/TCP: {t}")

    if len(nodes) > MAX_NODES:
        nodes = nodes[:MAX_NODES]
        print(f"Обрезано до {MAX_NODES}")

    Path("raw.txt").write_text("\n".join(nodes), encoding="utf-8")
    print(f"raw.txt — {len(nodes)} нод готово к тесту")


if __name__ == "__main__":
    asyncio.run(main())
