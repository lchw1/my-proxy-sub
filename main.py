import asyncio
import aiohttp
import re
import base64
import urllib.parse
import logging
import random
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def decode_base64(text: str) -> str:
    try:
        text = text.replace('\n', '').replace('\r', '').strip()
        padding = len(text) % 4
        if padding:
            text += '=' * (4 - padding)
        text = text.replace('-', '+').replace('_', '/')
        return base64.b64decode(text).decode('utf-8', errors='ignore')
    except Exception as e:
        return ""

async def fetch_source(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                text = await response.text()
                return text
            else:
                logging.warning(f"Failed to fetch {url}: HTTP {response.status}")
    except Exception as e:
        logging.warning(f"Error fetching {url}: {e}")
    return ""

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

            if "flow" in params:
                proxy["flow"] = params["flow"]

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
                proxy["reality-opts"] = {
                    "public-key": params.get("pbk", "")
                }
                if "sni" in params:
                    proxy["servername"] = params["sni"]
                if "fp" in params:
                    proxy["client-fingerprint"] = params["fp"]
                if "sid" in params:
                    proxy["reality-opts"]["short-id"] = params["sid"]

            if network == "ws":
                proxy["ws-opts"] = {
                    "path": params.get("path", "/"),
                    "headers": {
                        "Host": params.get("host", host)
                    }
                }
            elif network == "grpc":
                proxy["grpc-opts"] = {
                    "grpc-service-name": params.get("serviceName", "")
                }

        return proxy
    except Exception as e:
        return {}

async def get_all_proxies() -> List[Dict[str, Any]]:
    proxies = []
    try:
        with open("sources.txt", "r") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        logging.error("sources.txt not found")
        return []

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_source(session, url) for url in urls]
        results = await asyncio.gather(*tasks)

    for content in results:
        if not content:
            continue
        if not 'vless://' in content:
            decoded = decode_base64(content)
            if 'vless://' in decoded:
                content = decoded
        links = re.findall(r'(vless://[^\s]+)', content)
        for link in links:
            proxy = parse_vless_link(link)
            if proxy:
                proxies.append(proxy)

    logging.info(f"Extracted {len(proxies)} VLESS proxies in total")
    return proxies

import time
import os
import subprocess
import json
import urllib.request
from ruamel.yaml import YAML

async def download_mihomo():
    if not os.path.exists("mihomo"):
        logging.info("Downloading Mihomo core...")
        url = "https://github.com/MetaCubeX/mihomo/releases/download/v1.18.3/mihomo-linux-amd64-v1.18.3.gz"
        urllib.request.urlretrieve(url, "mihomo.gz")
        subprocess.run(["gunzip", "-f", "mihomo.gz"])
        os.chmod("mihomo", 0o755)

async def check_http(session: aiohttp.ClientSession, proxy: Dict[str, Any], api_port: int, sem: asyncio.Semaphore) -> tuple[Dict[str, Any], float]:
    url = f"http://127.0.0.1:{api_port}/proxies/{urllib.parse.quote(proxy['name'])}/delay"
    params = {
        "timeout": 3000,
        "url": "http://www.google.com/generate_204"
    }

    async with sem:
        try:
            async with session.get(url, params=params, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if "delay" in data:
                        return proxy, data["delay"]
        except Exception:
            pass
        return proxy, float('inf')

async def stage_2_check(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not proxies:
        return []

    await download_mihomo()
    logging.info(f"Starting Stage 2 HTTP latency check via Mihomo for {len(proxies)} proxies...")

    chunk_size = 400
    final_survivors = []

    for i in range(0, len(proxies), chunk_size):
        chunk = proxies[i:i + chunk_size]
        logging.info(f"Processing batch {i//chunk_size + 1} of {(len(proxies)-1)//chunk_size + 1} ({len(chunk)} proxies)...")

        yaml = YAML()
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.default_flow_style = False

        api_port = 9090
        mixed_port = 7890

        temp_config = {
            "port": mixed_port,
            "external-controller": f"127.0.0.1:{api_port}",
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
        results = []
        sem = asyncio.Semaphore(50) 

        async with aiohttp.ClientSession() as session:
            tasks = [check_http(session, proxy, api_port, sem) for proxy in chunk]
            results = await asyncio.gather(*tasks)

        process.terminate()
        process.wait()

        survivors = [(proxy, latency) for proxy, latency in results if latency < 3000]
        final_survivors.extend(survivors)
        
        await asyncio.sleep(1)

    if os.path.exists("temp_mihomo_config.yaml"):
        os.remove("temp_mihomo_config.yaml")

    final_survivors.sort(key=lambda x: x[1])
    logging.info(f"Stage 2 complete: {len(final_survivors)}/{len(proxies)} proxies survived.")

    final_proxies = []
    for proxy, latency in final_survivors:
        proxy['_latency'] = latency
        final_proxies.append(proxy)

    return final_proxies

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
    survivors = [proxy for proxy, is_alive in zip(proxies, results) if is_alive]
    logging.info(f"Stage 1 complete: {len(survivors)}/{len(proxies)} survived.")
    return survivors

async def resolve_countries(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    logging.info("Resolving countries via ip-api.com...")
    unique_servers = list(set(p['server'] for p in proxies))
    server_to_country = {}

    async with aiohttp.ClientSession() as session:
        # Разбиваем на пакеты по 100 штук (лимит API)
        for i in range(0, len(unique_servers), 100):
            chunk = unique_servers[i:i+100]
            data = [{"query": s} for s in chunk]
            try:
                async with session.post("http://ip-api.com/batch?fields=query,countryCode", json=data, timeout=10) as resp:
                    if resp.status == 200:
                        results = await resp.json()
                        for res in results:
                            if res.get("countryCode"):
                                server_to_country[res["query"]] = res["countryCode"]
            except Exception as e:
                logging.warning(f"GeoIP API error: {e}")
            await asyncio.sleep(2) # Защита от бана API

    for p in proxies:
        cc = server_to_country.get(p['server'], 'UNK')
        old_name = p['name']
        
        # Если имя просто vless-айпи:порт, сократим его, чтобы не было гигантским
        if old_name.startswith('vless-'):
            old_name = f"Node-{p['server'][-6:]}"
            
        p['name'] = f"[{cc}] {old_name}"

    return proxies

def sanitize_proxy_names(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_names = set()
    for proxy in proxies:
        # Теперь разрешаем квадратные скобки [] для стран
        clean_name = re.sub(r'[^\w\-\.\+\s\[\]\(\)\|]', '', proxy.get('name', 'Proxy'))
        clean_name = clean_name.strip()
        if not clean_name:
            clean_name = f"vless-{proxy.get('server')}-{proxy.get('port')}"

        final_name = clean_name
        counter = 1
        while final_name in seen_names:
            final_name = f"{clean_name}_{counter}"
            counter += 1

        seen_names.add(final_name)
        proxy['name'] = final_name
    return proxies

def deduplicate_proxies(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique_proxies = []
    for proxy in proxies:
        key = f"{proxy.get('server')}:{proxy.get('port')}:{proxy.get('uuid')}"
        if key not in seen:
            seen.add(key)
            unique_proxies.append(proxy)
    logging.info(f"Deduplicated down to {len(unique_proxies)} proxies")
    return unique_proxies # Переименовывать будем позже

def generate_yaml(proxies: List[Dict[str, Any]]):
    random.shuffle(proxies)

    for proxy in proxies:
        if '_latency' in proxy:
            del proxy['_latency']

    proxy_names = [proxy['name'] for proxy in proxies]

    config = {
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "SELECT",
                "type": "select",
                "proxies": ["URL-TEST", "FALLBACK"] + proxy_names
            },
            {
                "name": "URL-TEST",
                "type": "url-test",
                "url": "http://www.google.com/generate_204",
                "interval": 300,
                "proxies": proxy_names[:150] if len(proxy_names) >= 150 else proxy_names
            },
            {
                "name": "FALLBACK",
                "type": "fallback",
                "url": "http://www.google.com/generate_204",
                "interval": 300,
                "proxies": proxy_names
            }
        ],
        "rules": [
            "MATCH,SELECT"
        ]
    }

    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.default_flow_style = False

    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    logging.info(f"Generated config.yaml with {len(proxies)} proxies and routing rules.")

async def main():
    proxies = await get_all_proxies()
    proxies = deduplicate_proxies(proxies)
    proxies = await stage_1_check(proxies)
    proxies = await stage_2_check(proxies)
    proxies = await resolve_countries(proxies) # Пробиваем страны
    proxies = sanitize_proxy_names(proxies) # Чистим имена и гарантируем их уникальность
    generate_yaml(proxies)

if __name__ == "__main__":
    asyncio.run(main())
