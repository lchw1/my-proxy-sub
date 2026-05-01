"""
Сбор VLESS нод из источников параллельно.
Сохраняет raw.txt — все ноды для xray-knife теста.
Priority: Reality > WS/gRPC > TLS

Requirements: pip install aiohttp
"""

import asyncio
import base64
import re
import sys
import urllib.parse
from pathlib import Path

import aiohttp

SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/githubmirror/clean/vless.txt",
]

# Берём топ N нод на тест — больше не нужно
MAX_NODES = 2000

NODE_RE = re.compile(r"vless://[^\s\r\n'\"<>]+", re.IGNORECASE)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}


def node_priority(url: str) -> int:
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        sec = q.get("security", [""])[0].lower()
        net = q.get("type", [""])[0].lower()
        if sec == "reality":
            return 0   # лучший обход РКН
        if net in ("ws", "grpc"):
            return 1   # хорошо прячется под веб
    except Exception:
        pass
    return 2


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
        print(f"  {label}: {len(found)} vless")
        for node in found:
            if node not in seen:
                seen.add(node)
                nodes.append(node)

    total = len(nodes)
    print(f"\nВсего уникальных: {total}")

    # Сортируем по приоритету: Reality > WS/gRPC > TLS
    nodes.sort(key=node_priority)

    r = sum(1 for n in nodes if node_priority(n) == 0)
    w = sum(1 for n in nodes if node_priority(n) == 1)
    print(f"Reality: {r}  WS/gRPC: {w}  TLS/TCP: {total-r-w}")

    # Обрезаем — берём лучшие MAX_NODES
    if len(nodes) > MAX_NODES:
        nodes = nodes[:MAX_NODES]
        print(f"Обрезано до {MAX_NODES} для теста")

    Path("raw.txt").write_text("\n".join(nodes), encoding="utf-8")
    print(f"raw.txt сохранён — {len(nodes)} нод на тест")


if __name__ == "__main__":
    asyncio.run(main())
