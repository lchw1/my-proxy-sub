"""
Сбор VLESS нод.
Фокус: Reality-only, чтобы не кормить тестер мусором.
"""

import asyncio
import base64
import re
import urllib.parse
from pathlib import Path

import aiohttp

SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/githubmirror/clean/vless.txt",
    "https://raw.githubusercontent.com/kort0881/vpn-vless-configs-russia/main/githubmirror/clean/vless.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/4n0nymou3/multi-proxy-config-fetcher/main/configs/proxy_configs.txt",
    "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt",
]

# Важно: не даём тестеру захлебнуться.
MAX_NODES = 4000

NODE_RE = re.compile(r"vless://[^\s\r\n'\"<>]+", re.IGNORECASE)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}


def get_params(url: str):
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        sec = q.get("security", [""])[0].lower()
        net = q.get("type", [""])[0].lower()
        host = q.get("host", [""])[0].lower()
        sni = q.get("sni", [""])[0].lower()
        pbk = q.get("pbk", [""])[0]
        sid = q.get("sid", [""])[0]
        fp = q.get("fp", [""])[0].lower()
        return sec, net, host, sni, pbk, sid, fp
    except Exception:
        return "", "", "", "", "", "", ""


def is_useful(url: str) -> bool:
    sec, net, host, sni, pbk, sid, fp = get_params(url)

    # Жёсткий фокус на Reality.
    if sec != "reality":
        return False

    # Минимальная проверка на адекватность структуры.
    if not pbk or not sid:
        return False

    # Желательно наличие sni или host, иначе часто мусор.
    if not sni and not host:
        return False

    return True


def node_priority(url: str) -> int:
    sec, net, host, sni, pbk, sid, fp = get_params(url)

    # Reality с ws/grpc обычно чаще живёт.
    if sec == "reality" and net in ("ws", "grpc"):
        return 0
    if sec == "reality":
        return 1
    return 2


def decode_if_needed(text: str) -> str:
    lower_head = text[:2000].lower()
    if "vless://" in lower_head:
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


async def fetch_one(session: aiohttp.ClientSession, url: str) -> tuple[str, str]:
    label = url.split("/")[-1]
    try:
        timeout = aiohttp.ClientTimeout(connect=8, total=30)
        async with session.get(url, timeout=timeout) as r:
            if r.status == 200:
                return label, await r.text(encoding="utf-8", errors="ignore")
            print(f"SKIP {label} — HTTP {r.status}")
    except asyncio.TimeoutError:
        print(f"TIMEOUT {label}")
    except Exception as e:
        print(f"ERR {label} — {e}")
    return label, ""


def extract_nodes(text: str) -> list[str]:
    decoded = decode_if_needed(text)
    found = []
    for u in NODE_RE.findall(decoded):
        node = u.strip().rstrip("),.;]}'\"")
        if node.startswith("vless://") and is_useful(node):
            found.append(node)
    return found


async def main():
    print(f"Качаем {len(SOURCES)} источников...")

    connector = aiohttp.TCPConnector(limit=8, ttl_dns_cache=300)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        results = await asyncio.gather(*(fetch_one(session, u) for u in SOURCES))

    seen = set()
    nodes = []

    for label, text in results:
        if not text:
            continue
        found = extract_nodes(text)
        print(f"  {label}: {len(found)} reality-кандидатов")
        for node in found:
            if node not in seen:
                seen.add(node)
                nodes.append(node)

    # Стабильная сортировка: сначала более вероятно живые.
    nodes.sort(key=node_priority)

    # Не даём списку разрастись бесконечно.
    if len(nodes) > MAX_NODES:
        nodes = nodes[:MAX_NODES]
        print(f"Обрезано до MAX_NODES={MAX_NODES}")

    reality_cnt = sum(1 for n in nodes if node_priority(n) == 0)
    pure_cnt = sum(1 for n in nodes if node_priority(n) == 1)

    print(f"\nИтого кандидатов: {len(nodes)}")
    print(f"Reality+ws/grpc: {reality_cnt}")
    print(f"Reality only:     {pure_cnt}")

    Path("raw.txt").write_text("\n".join(nodes), encoding="utf-8")
    print("raw.txt готов")


if __name__ == "__main__":
    asyncio.run(main())
