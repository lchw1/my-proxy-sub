import asyncio
import aiohttp
import re
import base64
import urllib.parse
import logging
import random
import os
import subprocess
import urllib.request
import json
import html
import emoji
from typing import List, Dict, Any
from ruamel.yaml import YAML

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

COUNTRY_MAP = {
    "RU": ("🇷🇺", "Россия"), "DE": ("🇩🇪", "Германия"),
    "NL": ("🇳🇱", "Нидерланды"), "PL": ("🇵🇱", "Польша"),
    "US": ("🇺🇸", "США"), "FI": ("🇫🇮", "Финляндия"),
    "BE": ("🇧🇪", "Бельгия"), "ES": ("🇪🇸", "Испания"),
    "IT": ("🇮🇹", "Италия"), "KZ": ("🇰🇿", "Казахстан"),
    "LT": ("🇱🇹", "Литва"), "SG": ("🇸🇬", "Сингапур"),
    "CZ": ("🇨🇿", "Чехия"), "CH": ("🇨🇭", "Швейцария"),
    "SE": ("🇸🇪", "Швеция"), "EE": ("🇪🇪", "Эстония"),
    "CA": ("🇨🇦", "Канада"), "FR": ("🇫🇷", "Франция"),
    "GB": ("🇬🇧", "Великобритания"), "TR": ("🇹🇷", "Турция"),
    "UA": ("🇺🇦", "Украина"), "BG": ("🇧🇬", "Болгария"),
    "RO": ("🇷🇴", "Румыния"), "AT": ("🇦🇹", "Австрия"),
    "GE": ("🇬🇪", "Грузия"), "AE": ("🇦🇪", "ОАЭ"),
    "JP": ("🇯🇵", "Япония"), "KR": ("🇰🇷", "Южная Корея"),
    "HK": ("🇭🇰", "Гонконг"), "TW": ("🇹🇼", "Тайвань"),
    "TH": ("🇹🇭", "Таиланд"), "AL": ("🇦🇱", "Албания"),
    "IN": ("🇮🇳", "Индия"), "BR": ("🇧🇷", "Бразилия")
}

COUNTRY_KEYWORDS = {
    "russia": "RU", "россия": "RU", "moscow": "RU", "sbrf": "RU",
    "germany": "DE", "германия": "DE", "frankfurt": "DE", "gernode": "DE",
    "netherlands": "NL", "нидерланды": "NL", "amsterdam": "NL",
    "poland": "PL", "польша": "PL",
    "usa": "US", "united states": "US", "сша": "US", "america": "US",
    "finland": "FI", "финляндия": "FI", "helsinki": "FI",
    "belgium": "BE", "бельгия": "BE",
    "spain": "ES", "испания": "ES",
    "italy": "IT", "италия": "IT",
    "kazakhstan": "KZ", "казахстан": "KZ", "astana": "KZ",
    "lithuania": "LT", "литва": "LT", "lithnode": "LT",
    "singapore": "SG", "сингапур": "SG",
    "czechia": "CZ", "чехия": "CZ", "cznode": "CZ",
    "switzerland": "CH", "швейцария": "CH",
    "sweden": "SE", "швеция": "SE", "swed": "SE",
    "estonia": "EE", "эстония": "EE",
    "canada": "CA", "канада": "CA",
    "france": "FR", "франция": "FR", "paris": "FR",
    "united kingdom": "GB", "великобритания": "GB", "london": "GB", "england": "GB",
    "turkey": "TR", "турция": "TR",
    "ukraine": "UA", "украина": "UA",
    "bulgaria": "BG", "болгария": "BG",
    "romania": "RO", "румыния": "RO",
    "austria": "AT", "австрия": "AT",
    "georgia": "GE", "грузия": "GE", "tbilisi": "GE", "georg": "GE",
    "uae": "AE", "оаэ": "AE",
    "japan": "JP", "япония": "JP", "tokyo": "JP",
    "korea": "KR", "южная корея": "KR", "seoul": "KR",
    "hong kong": "HK", "гонконг": "HK",
    "taiwan": "TW", "тайвань": "TW",
    "thailand": "TH", "таиланд": "TH",
    "albania": "AL", "албания": "AL",
    "india": "IN", "индия": "IN",
    "brazil": "BR", "бразилия": "BR"
}


def cc_to_flag(cc: str) -> str:
    if not cc or len(cc) != 2 or cc == 'UN':
        return "🏳️"
    return chr(ord(cc[0].upper()) + 127397) + chr(ord(cc[1].upper()) + 127397)


def decode_base64(text: str) -> str:
    try:
        text = text.replace('\n', '').replace('\r', '').strip()
        padding = len(text) % 4
        if padding:
            text += '=' * (4 - padding)
        text = text.replace('-', '+').replace('_', '/')
        return base64.b64decode(text).decode('utf-8', errors='ignore')
    except Exception:
        return ""


async def fetch_source(session: aiohttp.ClientSession, url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(url, headers=headers, timeout=timeout) as response:
            if response.status == 200:
                return await response.text()
    except Exception as e:
        logging.debug(f"Error fetching {url}: {e}")
    return ""


# ─────────────────────────── VLESS ───────────────────────────

def parse_vless_link(link: str) -> Dict[str, Any]:
    try:
        match = re.match(r'^vless://([^@]+)@([^:]+):(\d+)(?:\?([^#]*))?(?:#(.*))?$', link)
        if not match:
            return {}

        uuid, host, port, query_string, name = match.groups()

        proxy = {
            "name": urllib.parse.unquote(name) if name else f"vless-{host}:{port}",
            "type": "vless",
            "server": host,
            "port": int(port),
            "uuid": uuid,
            "udp": True,
        }

        if query_string:
            params = dict(urllib.parse.parse_qsl(query_string))

            network = params.get("type", "tcp")
            if network in ["vless", "vmess"]:
                network = "tcp"
            proxy["network"] = network

            security = params.get("security", "")
            if security == "tls":
                proxy["tls"] = True
                if "sni" in params:
                    proxy["servername"] = params["sni"]
                if "fp" in params:
                    proxy["client-fingerprint"] = params["fp"]
                if "alpn" in params:
                    proxy["alpn"] = params["alpn"].split(',')
            elif security == "reality":
                proxy["tls"] = True
                proxy["reality-opts"] = {"public-key": params.get("pbk", "")}
                if "sni" in params:
                    proxy["servername"] = params["sni"]
                if "fp" in params:
                    proxy["client-fingerprint"] = params["fp"]
                if "sid" in params:
                    proxy["reality-opts"]["short-id"] = params["sid"]

            if "flow" in params and security in ["tls", "reality"]:
                proxy["flow"] = params["flow"]

            if network == "ws":
                proxy["ws-opts"] = {
                    "path": params.get("path", "/"),
                    "headers": {"Host": params.get("host", host)}
                }
            elif network == "grpc":
                proxy["grpc-opts"] = {
                    "grpc-service-name": params.get("serviceName", "")
                }

        return proxy
    except Exception:
        return {}


# ─────────────────────────── VMESS ───────────────────────────

def parse_vmess_link(link: str) -> Dict[str, Any]:
    try:
        b64 = link[len("vmess://"):]
        decoded = decode_base64(b64)
        if not decoded:
            return {}
        data = json.loads(decoded)

        port = int(data.get("port", 443))
        name = data.get("ps") or f"{data.get('add', '')}:{port}"

        proxy = {
            "name": name,
            "type": "vmess",
            "server": data.get("add", ""),
            "port": port,
            "uuid": data.get("id", ""),
            "alterId": int(data.get("aid", 0)),
            "cipher": data.get("scy") or data.get("cipher") or "auto",
            "udp": True,
        }

        network = data.get("net", "tcp")
        proxy["network"] = network

        tls = str(data.get("tls", "")).lower()
        if tls == "tls":
            proxy["tls"] = True
            if data.get("sni"):
                proxy["servername"] = data["sni"]
            if data.get("fp"):
                proxy["client-fingerprint"] = data["fp"]
            if data.get("alpn"):
                proxy["alpn"] = data["alpn"].split(',') if isinstance(data["alpn"], str) else data["alpn"]

        if network == "ws":
            proxy["ws-opts"] = {
                "path": data.get("path", "/"),
                "headers": {"Host": data.get("host", data.get("add", ""))}
            }
        elif network == "grpc":
            proxy["grpc-opts"] = {"grpc-service-name": data.get("path", "")}
        elif network == "h2":
            proxy["h2-opts"] = {
                "host": [data.get("host", data.get("add", ""))],
                "path": data.get("path", "/")
            }

        if not proxy["server"] or not proxy["uuid"]:
            return {}

        return proxy
    except Exception:
        return {}


# ─────────────────────────── HYSTERIA 2 ───────────────────────────

def parse_hy2_link(link: str) -> Dict[str, Any]:
    try:
        rest = link[len("hysteria2://") if link.startswith("hysteria2://") else len("hy2://"):]
        match = re.match(r'^([^@]+)@([^:/?#]+):(\d+)(?:\?([^#]*))?(?:#(.*))?$', rest)
        if not match:
            return {}

        password, host, port, query_string, name = match.groups()

        proxy = {
            "name": urllib.parse.unquote(name) if name else f"hy2-{host}:{port}",
            "type": "hysteria2",
            "server": host,
            "port": int(port),
            "password": urllib.parse.unquote(password),
            "udp": True,
        }

        if query_string:
            params = dict(urllib.parse.parse_qsl(query_string))
            if "sni" in params:
                proxy["sni"] = params["sni"]
            if params.get("insecure", "0") == "1":
                proxy["skip-cert-verify"] = True
            if "obfs" in params:
                proxy["obfs"] = params["obfs"]
                if "obfs-password" in params:
                    proxy["obfs-password"] = params["obfs-password"]

        return proxy
    except Exception:
        return {}


# ─────────────────────────── СБОРКА ───────────────────────────

async def get_all_proxies() -> List[Dict[str, Any]]:
    proxies = []
    try:
        with open("sources.txt", "r") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_source(session, url) for url in urls]
        results = await asyncio.gather(*tasks)

    for content in results:
        if not content:
            continue

        content = html.unescape(content)

        has_proxy = any(p in content for p in ('vless://', 'vmess://', 'hysteria2://', 'hy2://'))
        if not has_proxy:
            decoded = decode_base64(content)
            if any(p in decoded for p in ('vless://', 'vmess://', 'hysteria2://', 'hy2://')):
                content = html.unescape(decoded)

        for link in re.findall(r'(vless://[^\s"\'<>&\u0000-\u001F]+)', content):
            p = parse_vless_link(link)
            if p:
                proxies.append(p)

        for link in re.findall(r'(vmess://[^\s"\'<>&\u0000-\u001F]+)', content):
            p = parse_vmess_link(link)
            if p:
                proxies.append(p)

        for link in re.findall(r'((?:hysteria2|hy2)://[^\s"\'<>&\u0000-\u001F]+)', content):
            p = parse_hy2_link(link)
            if p:
                proxies.append(p)

    vless_count = sum(1 for p in proxies if p.get("type") == "vless")
    vmess_count = sum(1 for p in proxies if p.get("type") == "vmess")
    hy2_count   = sum(1 for p in proxies if p.get("type") == "hysteria2")
    logging.info(f"Extracted {len(proxies)} proxies total: {vless_count} VLESS, {vmess_count} VMess, {hy2_count} Hy2")
    return proxies


def sanitize_proxy_names(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_names = set()
    for proxy in proxies:
        clean_name = re.sub(r'[\r\n\t"\'<>\\]', '', proxy.get('name', 'Proxy'))
        clean_name = clean_name.strip()
        if not clean_name:
            clean_name = f"{proxy.get('type', 'proxy')}-{proxy.get('server')}-{proxy.get('port')}"

        final_name = clean_name
        counter = 1
        while final_name in seen_names:
            final_name = f"{clean_name} {counter}"
            counter += 1
        seen_names.add(final_name)
        proxy['name'] = final_name
    return proxies


def deduplicate_proxies(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for p in proxies:
        secret = p.get('uuid') or p.get('password', '')
        key = f"{p.get('type')}:{p.get('server')}:{p.get('port')}:{secret}"
        if key not in seen:
            seen.add(key)
            unique.append(p)
    logging.info(f"Deduplicated down to {len(unique)} proxies")
    # sanitize здесь не вызываем — имена всё равно перезапишет resolve_countries
    return unique


async def check_tcp(proxy: Dict[str, Any]) -> bool:
    try:
        host = proxy.get('server')
        port = proxy.get('port')
        conn = asyncio.open_connection(host, port)
        # reader не нужен — используем _ чтобы явно обозначить что переменная игнорируется
        _, writer = await asyncio.wait_for(conn, timeout=3.0)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def stage_1_check(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    logging.info(f"Starting Stage 1 TCP check for {len(proxies)} proxies...")
    tasks = [check_tcp(proxy) for proxy in proxies]
    results = await asyncio.gather(*tasks)
    survivors = [p for p, is_alive in zip(proxies, results) if is_alive]
    logging.info(f"Stage 1 complete: {len(survivors)}/{len(proxies)} survived TCP check.")
    return survivors


async def check_http(
    session: aiohttp.ClientSession,
    proxy: Dict[str, Any],
    api_port: int,
    sem: asyncio.Semaphore
):
    url = f"http://127.0.0.1:{api_port}/proxies/{urllib.parse.quote(proxy['name'])}/delay"
    params = {"timeout": 7000, "url": "http://www.gstatic.com/generate_204"}
    async with sem:
        try:
            timeout = aiohttp.ClientTimeout(total=12)
            async with session.get(url, params=params, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "delay" in data and data["delay"] > 0:
                        return proxy, data["delay"]
        except Exception:
            pass
        return proxy, float('inf')


async def stage_2_check(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not proxies:
        return []

    if not os.path.exists("mihomo"):
        logging.info("Downloading Mihomo core...")
        urllib.request.urlretrieve(
            "https://github.com/MetaCubeX/mihomo/releases/download/v1.18.3/mihomo-linux-amd64-v1.18.3.gz",
            "mihomo.gz"
        )
        subprocess.run(["gunzip", "-f", "mihomo.gz"])
        os.chmod("mihomo", 0o755)

    logging.info(f"Starting Stage 2 HTTP latency check via Mihomo for {len(proxies)} proxies...")
    chunk_size = 100
    final_survivors = []

    # YAML-объект создаём один раз за пределами цикла
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.default_flow_style = False

    # Один ClientSession на все батчи
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(proxies), chunk_size):
            chunk = proxies[i:i + chunk_size]
            logging.info(
                f"Processing batch {i // chunk_size + 1} of "
                f"{(len(proxies) - 1) // chunk_size + 1} ({len(chunk)} proxies)..."
            )

            temp_config = {
                "port": 7890,
                "external-controller": "127.0.0.1:9090",
                "mode": "rule",
                "proxies": chunk,
                "proxy-groups": [
                    {"name": "PROXY", "type": "select", "proxies": [p["name"] for p in chunk]}
                ],
                "rules": ["MATCH,PROXY"]
            }

            with open("temp_mihomo_config.yaml", "w", encoding="utf-8") as f:
                yaml.dump(temp_config, f)

            process = subprocess.Popen(
                ["./mihomo", "-f", "temp_mihomo_config.yaml"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            await asyncio.sleep(10)

            sem = asyncio.Semaphore(30)
            tasks = [check_http(session, p, 9090, sem) for p in chunk]
            results = await asyncio.gather(*tasks)

            process.terminate()
            process.wait()

            survivors = [(p, lat) for p, lat in results if lat < 8000]
            final_survivors.extend(survivors)
            await asyncio.sleep(3)

    if os.path.exists("temp_mihomo_config.yaml"):
        os.remove("temp_mihomo_config.yaml")

    final_survivors.sort(key=lambda x: x[1])
    logging.info(f"Stage 2 complete: {len(final_survivors)}/{len(proxies)} proxies survived.")

    final_proxies = []
    for p, lat in final_survivors:
        if '_latency' in p:
            del p['_latency']
        final_proxies.append(p)
    return final_proxies


def extract_country_from_name(name: str) -> str:
    # ФИКС: флаг-эмодзи состоит из двух Unicode-кодпоинтов (региональных индикаторов).
    # При итерации по строке Python отдаёт каждый кодпоинт по одному (len==1),
    # поэтому len(char)==2 никогда не выполнялось. Используем emoji.emoji_list()
    # который правильно группирует многокодпоинтные последовательности.
    for item in emoji.emoji_list(name):
        e = item['emoji']
        codepoints = [ord(c) for c in e]
        if len(codepoints) == 2 and all(0x1F1E6 <= cp <= 0x1F1FF for cp in codepoints):
            cc = chr(codepoints[0] - 127397) + chr(codepoints[1] - 127397)
            if cc in COUNTRY_MAP:
                return cc

    text_name = name.lower()
    match = re.search(r'\[([a-z]{2})\]', text_name)
    if match and match.group(1).upper() in COUNTRY_MAP:
        return match.group(1).upper()

    for keyword, cc in COUNTRY_KEYWORDS.items():
        if re.search(rf'\b{keyword}\b', text_name):
            return cc

    return 'UN'


async def resolve_countries(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not proxies:
        return []
    logging.info("Определяем страны (Анализ имен + ip-api.com с учетом CDN)...")

    geo_map = {}
    ips_to_check = []

    for p in proxies:
        cc = extract_country_from_name(p['name'])
        if cc == 'UN':
            ips_to_check.append(p['server'])
        else:
            p['_resolved_cc'] = cc

    unique_ips = list(set(ips_to_check))

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(unique_ips), 100):
            chunk = unique_ips[i:i + 100]
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with session.post(
                    "http://ip-api.com/batch?fields=query,countryCode,org",
                    json=[{"query": ip} for ip in chunk],
                    timeout=timeout
                ) as r:
                    if r.status == 200:
                        for item in await r.json():
                            if 'Cloudflare' in item.get('org', ''):
                                geo_map[item['query']] = 'UN'
                            else:
                                geo_map[item['query']] = item.get('countryCode', 'UN')
                    else:
                        logging.warning(f"IP-API returned {r.status}")
            except Exception as e:
                logging.debug(f"GeoIP Error: {e}")

            # Лимит ip-api.com: 15 батч-запросов в минуту
            await asyncio.sleep(4.5)

    for p in proxies:
        cc = p.pop('_resolved_cc', 'UN')
        if cc == 'UN':
            api_cc = geo_map.get(p['server'], 'UN')
            if api_cc in COUNTRY_MAP:
                cc = api_cc

        flag, c_name = COUNTRY_MAP.get(cc, (cc_to_flag(cc), cc if cc != 'UN' else "Неизвестно"))
        p['name'] = f"{flag} {c_name}"

    return proxies


def generate_yaml(proxies: List[Dict[str, Any]]):
    if not proxies:
        logging.error("0 PROXIES PASSED! CONFIG WILL BE EMPTY.")

    random.shuffle(proxies)
    proxies = proxies[:600]

    all_proxy_names = [p['name'] for p in proxies]
    ru_names      = [n for n in all_proxy_names if "Россия" in n]
    foreign_names = [n for n in all_proxy_names if "Россия" not in n]

    config = {
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "🚀 Главный Выбор",
                "type": "select",
                "proxies": [
                    "🤖 Авто-режимы",
                    "🌐 Все серверы (Ручной)",
                    "🌍 Зарубеж (Ручной)",
                    "🐻 Россия (Ручной)",
                    "DIRECT"
                ]
            },
            {
                "name": "🤖 Авто-режимы",
                "type": "select",
                "proxies": [
                    "⚡ Лучший пинг (Все)",
                    "⚡ Авто-Зарубеж",
                    "⚡ Авто-Россия"
                ]
            },
            {
                "name": "🌐 Все серверы (Ручной)",
                "type": "select",
                "proxies": all_proxy_names if all_proxy_names else ["DIRECT"]
            },
            {
                "name": "🌍 Зарубеж (Ручной)",
                "type": "select",
                "proxies": foreign_names if foreign_names else ["DIRECT"]
            },
            {
                "name": "🐻 Россия (Ручной)",
                "type": "select",
                "proxies": ru_names if ru_names else ["DIRECT"]
            },
            {
                "name": "⚡ Лучший пинг (Все)",
                "type": "url-test",
                "hidden": True,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 150,
                "proxies": (
                    all_proxy_names[:150] if len(all_proxy_names) >= 150
                    else (all_proxy_names if all_proxy_names else ["DIRECT"])
                )
            },
            {
                "name": "⚡ Авто-Зарубеж",
                "type": "url-test",
                "hidden": True,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 150,
                "proxies": (
                    foreign_names[:150] if len(foreign_names) >= 150
                    else (foreign_names if foreign_names else ["DIRECT"])
                )
            },
            {
                "name": "⚡ Авто-Россия",
                "type": "url-test",
                "hidden": True,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 150,
                "proxies": ru_names if ru_names else ["DIRECT"]
            }
        ],
        "rules": [
            "MATCH,🚀 Главный Выбор"
        ]
    }

    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.default_flow_style = False
    yaml.representer.ignore_aliases = lambda *data: True

    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    logging.info(f"Generated config.yaml with {len(proxies)} proxies.")

    stats = {"total": len(proxies), "countries": {}}
    for p in proxies:
        parts = p['name'].split(' ')
        if len(parts) >= 2:
            country_name = f"{parts[0]} {parts[1]}"
            stats["countries"][country_name] = stats["countries"].get(country_name, 0) + 1

    stats["countries"] = dict(
        sorted(stats["countries"].items(), key=lambda item: item[1], reverse=True)
    )

    with open("stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    logging.info("Generated stats.json for website.")


async def main():
    proxies = await get_all_proxies()
    proxies = deduplicate_proxies(proxies)
    proxies = await stage_1_check(proxies)
    proxies = await stage_2_check(proxies)
    proxies = await resolve_countries(proxies)
    # sanitize вызываем один раз — после того как resolve_countries проставил финальные имена
    proxies = sanitize_proxy_names(proxies)
    generate_yaml(proxies)


if __name__ == "__main__":
    asyncio.run(main())
