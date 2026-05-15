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
from typing import List, Dict, Any
from ruamel.yaml import YAML

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Полный словарь стран с красивыми названиями и флагами
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

# Словарь для умного поиска стран по тексту (доменам и названиям)
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
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                return await response.text()
    except Exception as e:
        logging.debug(f"Error fetching {url}: {e}")
    return ""

def parse_vless_link(link: str) -> Dict[str, Any]:
    try:
        match = re.match(r'^vless://([^@]+)@([^:]+):(\d+)(?:\?([^#]*))?(?:#(.*))?$', link)
        if not match: return {}

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
            if network in ["vless", "vmess"]: network = "tcp"
            proxy["network"] = network

            security = params.get("security", "")
            if security == "tls":
                proxy["tls"] = True
                if "sni" in params: proxy["servername"] = params["sni"]
                if "fp" in params: proxy["client-fingerprint"] = params["fp"]
                if "alpn" in params: proxy["alpn"] = params["alpn"].split(',')
            elif security == "reality":
                proxy["tls"] = True
                proxy["reality-opts"] = {"public-key": params.get("pbk", "")}
                if "sni" in params: proxy["servername"] = params["sni"]
                if "fp" in params: proxy["client-fingerprint"] = params["fp"]
                if "sid" in params: proxy["reality-opts"]["short-id"] = params["sid"]

            if "flow" in params and security in ["tls", "reality"]:
                proxy["flow"] = params["flow"]

            if network == "ws":
                proxy["ws-opts"] = {
                    "path": params.get("path", "/"),
                    "headers": {"Host": params.get("host", host)}
                }
            elif network == "grpc":
                proxy["grpc-opts"] = {"grpc-service-name": params.get("serviceName", "")}

        return proxy
    except Exception:
        return {}

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
        if not content: continue
        if not 'vless://' in content:
            decoded = decode_base64(content)
            if 'vless://' in decoded: content = decoded
        links = re.findall(r'(vless://[^\s]+)', content)
        for link in links:
            p = parse_vless_link(link)
            if p: proxies.append(p)

    logging.info(f"Extracted {len(proxies)} VLESS proxies in total")
    return proxies

def sanitize_proxy_names(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_names = set()
    for proxy in proxies:
        clean_name = re.sub(r'[\r\n\t"\'<>\\]', '', proxy.get('name', 'Proxy'))
        clean_name = clean_name.strip()
        if not clean_name: clean_name = f"vless-{proxy.get('server')}-{proxy.get('port')}"

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
        key = f"{p.get('server')}:{p.get('port')}:{p.get('uuid')}"
        if key not in seen:
            seen.add(key)
            unique.append(p)
    logging.info(f"Deduplicated down to {len(unique)} proxies")
    return sanitize_proxy_names(unique)

async def check_tcp(proxy: Dict[str, Any]) -> bool:
    try:
        host = proxy.get('server')
        port = proxy.get('port')
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=3.0)
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

async def check_http(session: aiohttp.ClientSession, proxy: Dict[str, Any], api_port: int, sem: asyncio.Semaphore):
    url = f"http://127.0.0.1:{api_port}/proxies/{urllib.parse.quote(proxy['name'])}/delay"
    params = {"timeout": 3000, "url": "http://www.gstatic.com/generate_204"}
    async with sem:
        try:
            async with session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "delay" in data:
                        return proxy, data["delay"]
        except Exception:
            pass
        return proxy, float('inf')

async def stage_2_check(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not proxies: return []
    if not os.path.exists("mihomo"):
        logging.info("Downloading Mihomo core...")
        urllib.request.urlretrieve("https://github.com/MetaCubeX/mihomo/releases/download/v1.18.3/mihomo-linux-amd64-v1.18.3.gz", "mihomo.gz")
        subprocess.run(["gunzip", "-f", "mihomo.gz"])
        os.chmod("mihomo", 0o755)

    logging.info(f"Starting Stage 2 HTTP latency check via Mihomo for {len(proxies)} proxies...")
    chunk_size = 400
    final_survivors = []

    for i in range(0, len(proxies), chunk_size):
        chunk = proxies[i:i + chunk_size]
        logging.info(f"Processing batch {i//chunk_size + 1} of {(len(proxies)-1)//chunk_size + 1} ({len(chunk)} proxies)...")

        yaml = YAML()
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.default_flow_style = False

        temp_config = {
            "port": 7890,
            "external-controller": "127.0.0.1:9090",
            "mode": "rule",
            "proxies": chunk,
            "proxy-groups": [{"name": "PROXY", "type": "select", "proxies": [p["name"] for p in chunk]}],
            "rules": ["MATCH,PROXY"]
        }

        with open("temp_mihomo_config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(temp_config, f)

        process = subprocess.Popen(
            ["./mihomo", "-f", "temp_mihomo_config.yaml"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        await asyncio.sleep(5)

        sem = asyncio.Semaphore(50)
        async with aiohttp.ClientSession() as session:
            tasks = [check_http(session, p, 9090, sem) for p in chunk]
            results = await asyncio.gather(*tasks)

        process.terminate()
        process.wait()

        survivors = [(p, lat) for p, lat in results if lat < 3000]
        final_survivors.extend(survivors)
        await asyncio.sleep(1)

    if os.path.exists("temp_mihomo_config.yaml"):
        os.remove("temp_mihomo_config.yaml")

    final_survivors.sort(key=lambda x: x[1])
    logging.info(f"Stage 2 complete: {len(final_survivors)}/{len(proxies)} proxies survived.")

    final_proxies = []
    for p, lat in final_survivors:
        if '_latency' in p: del p['_latency']
        final_proxies.append(p)
    return final_proxies

def guess_country(old_name: str, server: str) -> str:
    text_name = old_name.lower()
    match = re.search(r'\[([a-z]{2})\]', text_name)
    if match and match.group(1).upper() in COUNTRY_MAP:
        return match.group(1).upper()

    for keyword, cc in COUNTRY_KEYWORDS.items():
        if re.search(rf'\b{keyword}\b', text_name):
            return cc

    parts = re.split(r'[\.\-]', server.lower())
    for part in parts:
        if part in COUNTRY_KEYWORDS:
            return COUNTRY_KEYWORDS[part]
        if len(part) == 2 and part.upper() in COUNTRY_MAP:
            return part.upper()

    return 'UN'

async def resolve_countries(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not proxies: return []
    logging.info("Определяем страны (Умный анализ + API)...")
    unique_ips = list(set(p['server'] for p in proxies))
    geo_map = {}
    
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(unique_ips), 100):
            chunk = unique_ips[i:i+100]
            try:
                async with session.post("http://ip-api.com/batch?fields=query,countryCode", json=[{"query": ip} for ip in chunk]) as r:
                    if r.status == 200:
                        for item in await r.json():
                            geo_map[item['query']] = item.get('countryCode', 'UN')
            except Exception as e:
                logging.debug(f"GeoIP Error: {e}")
            await asyncio.sleep(1.5)

    for p in proxies:
        host = p['server']
        old_name = p['name']
        
        cc = guess_country(old_name, host)
        
        if cc == 'UN':
            api_cc = geo_map.get(host, 'UN')
            if api_cc in COUNTRY_MAP:
                cc = api_cc
            elif api_cc != 'UN':
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
    
    ru_names = [name for name in all_proxy_names if "Россия" in name]
    foreign_names = [name for name in all_proxy_names if "Россия" not in name]

    config = {
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "🚀 Главный Выбор",
                "type": "select",
                "proxies": [
                    "🤖 Авто-режимы",
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
                "url": "http://www.gstatic.com/generate_204",
                "interval": 150,
                "proxies": all_proxy_names[:150] if len(all_proxy_names) >= 150 else (all_proxy_names if all_proxy_names else ["DIRECT"])
            },
            {
                "name": "⚡ Авто-Зарубеж",
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 150,
                "proxies": foreign_names[:150] if len(foreign_names) >= 150 else (foreign_names if foreign_names else ["DIRECT"])
            },
            {
                "name": "⚡ Авто-Россия",
                "type": "url-test",
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
    
    # Отключаем алиасы, чтобы папки-балансировщики работали во всех клиентах
    yaml.representer.ignore_aliases = lambda *data: True

    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    logging.info(f"Generated config.yaml with {len(proxies)} proxies.")

async def main():
    proxies = await get_all_proxies()
    proxies = deduplicate_proxies(proxies)
    proxies = await stage_1_check(proxies)
    proxies = await stage_2_check(proxies)
    proxies = await resolve_countries(proxies)
    proxies = sanitize_proxy_names(proxies)
    generate_yaml(proxies)

if __name__ == "__main__":
    asyncio.run(main())
