import asyncio
import aiohttp
import re
import base64
import urllib.parse
import logging
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def decode_base64(text: str) -> str:
    try:
        text = text.replace('\n', '').replace('\r', '').strip()
        # Add padding if needed
        padding = len(text) % 4
        if padding:
            text += '=' * (4 - padding)
        # Handle standard and url-safe base64
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
    # vless://uuid@host:port?query#name
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

            # Map type to network
            network = params.get("type", "tcp")
            if network in ["vless", "vmess"]:
                network = "tcp"
            proxy["network"] = network

            # Handle security (tls/reality)
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

            # Handle network specific options
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
        logging.debug(f"Failed to parse link {link[:30]}...: {e}")
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

        # Determine if content is likely base64 encoded
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

async def check_http(session: aiohttp.ClientSession, proxy: Dict[str, Any], api_port: int) -> tuple[Dict[str, Any], float]:
    url = f"http://127.0.0.1:{api_port}/proxies/{urllib.parse.quote(proxy['name'])}/delay"
    params = {
        "timeout": 3000,
        "url": "http://www.google.com/generate_204"
    }

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

    # Generate temporary config for Mihomo
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.default_flow_style = False

    api_port = 9090
    mixed_port = 7890

    temp_config = {
        "port": mixed_port,
        "external-controller": f"127.0.0.1:{api_port}",
        "mode": "rule",
        "proxies": proxies,
        "proxy-groups": [{"name": "PROXY", "type": "select", "proxies": [p["name"] for p in proxies]}],
        "rules": ["MATCH,PROXY"]
    }

    with open("temp_mihomo_config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(temp_config, f)

    # Start Mihomo
    process = subprocess.Popen(
        ["./mihomo", "-f", "temp_mihomo_config.yaml"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Wait for Mihomo to start
    await asyncio.sleep(2)

    results = []
    async with aiohttp.ClientSession() as session:
        # We need to process sequentially or in batches to avoid overwhelming Mihomo,
        # but gather is usually fine for a few dozen. For hundreds, we batch.
        batch_size = 50
        for i in range(0, len(proxies), batch_size):
            batch = proxies[i:i+batch_size]
            tasks = [check_http(session, proxy, api_port) for proxy in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            await asyncio.sleep(0.5)

    # Stop Mihomo
    process.terminate()
    process.wait()

    if os.path.exists("temp_mihomo_config.yaml"):
        os.remove("temp_mihomo_config.yaml")

    # Filter out failures and sort by latency
    survivors = [(proxy, latency) for proxy, latency in results if latency < 3000] # less than 3s
    survivors.sort(key=lambda x: x[1])

    logging.info(f"Stage 2 complete: {len(survivors)}/{len(proxies)} proxies survived real traffic check.")

    final_proxies = []
    for proxy, latency in survivors:
        proxy['_latency'] = latency
        final_proxies.append(proxy)

    return final_proxies

async def check_tcp(proxy: Dict[str, Any]) -> bool:
    try:
        host = proxy.get('server')
        port = proxy.get('port')

        # Async TCP connection check with 3s timeout
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
    logging.info(f"Stage 1 complete: {len(survivors)}/{len(proxies)} proxies survived TCP check.")
    return survivors

def deduplicate_proxies(proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique_proxies = []
    for proxy in proxies:
        # Create a unique key based on IP/Host, Port, and UUID
        key = f"{proxy.get('server')}:{proxy.get('port')}:{proxy.get('uuid')}"
        if key not in seen:
            seen.add(key)
            unique_proxies.append(proxy)
    logging.info(f"Deduplicated down to {len(unique_proxies)} proxies")
    return unique_proxies

from ruamel.yaml import YAML

def generate_yaml(proxies: List[Dict[str, Any]]):
    # Limit to top 600
    proxies = proxies[:600]

    # Remove internal latency key
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
                "proxies": proxy_names[:50] if len(proxy_names) >= 50 else proxy_names
            },
            {
                "name": "FALLBACK",
                "type": "fallback",
                "url": "http://www.google.com/generate_204",
                "interval": 300,
                "proxies": proxy_names
            }
        ]
    }

    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.default_flow_style = False

    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    logging.info(f"Generated config.yaml with {len(proxies)} proxies.")

async def main():
    proxies = await get_all_proxies()
    proxies = deduplicate_proxies(proxies)
    proxies = await stage_1_check(proxies)
    proxies = await stage_2_check(proxies)
    generate_yaml(proxies)

if __name__ == "__main__":
    asyncio.run(main())
