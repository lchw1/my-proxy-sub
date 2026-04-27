import requests
import base64
import re
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

SOURCES = {
    "🏴 ЧС полный (ПК)":         "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "🏴 ЧС мобильный":           "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "⚪ БС CIDR полный (ПК)":    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_CIDR_RUS.txt",
    "⚪ БС CIDR мобильный":      "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_CIDR_RUS_mobile.txt",
    "⚪ БС SNI":                  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_SNI_RUS.txt",
    "🌐 Yebekhe VLESS":          "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/vless",
}

def try_decode_base64(content):
    if "vless://" in content[:300]:
        return content
    try:
        text = content.strip().replace('\n', '').replace('\r', '')
        pad = len(text) % 4
        if pad:
            text += '=' * (4 - pad)
        return base64.b64decode(text).decode('utf-8', errors='ignore')
    except Exception:
        return content

def parse_vless_to_clash(vless_url, index):
    """Конвертирует vless:// строку в словарь для Clash YAML"""
    try:
        # vless://uuid@host:port?params#name
        match = re.match(r'vless://([^@]+)@([^:]+):(\d+)\??([^#]*)#?(.*)', vless_url)
        if not match:
            return None

        uuid, host, port, params_str, name = match.groups()
        port = int(port)

        # Парсим параметры
        params = {}
        if params_str:
            for p in params_str.split('&'):
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v

        # Имя прокси — берём из #name или генерируем
        proxy_name = name.strip() if name.strip() else f"vless-{index}"
        # Убираем emoji и спецсимволы из имени для совместимости
        proxy_name = re.sub(r'[^\w\s\-\.,@#\[\]()]', '', proxy_name).strip()
        if not proxy_name:
            proxy_name = f"vless-{index}"

        proxy = {
            "name": proxy_name,
            "type": "vless",
            "server": host,
            "port": port,
            "uuid": uuid,
            "tls": params.get("security") in ("tls", "reality"),
            "udp": True,
            "skip-cert-verify": True,
        }

        # Network type (tcp/ws/grpc)
        network = params.get("type", "tcp")
        if network == "ws":
            proxy["network"] = "ws"
            ws_opts = {}
            if params.get("path"):
                ws_opts["path"] = params["path"]
            if params.get("host"):
                ws_opts["headers"] = {"Host": params["host"]}
            if ws_opts:
                proxy["ws-opts"] = ws_opts
        elif network == "grpc":
            proxy["network"] = "grpc"
            if params.get("serviceName"):
                proxy["grpc-opts"] = {"grpc-service-name": params["serviceName"]}

        # XTLS / flow
        if params.get("flow"):
            proxy["flow"] = params["flow"]

        # Reality
        if params.get("security") == "reality":
            proxy["reality-opts"] = {
                "public-key": params.get("pbk", ""),
                "short-id": params.get("sid", ""),
            }
            if params.get("sni"):
                proxy["servername"] = params["sni"]
            if params.get("fp"):
                proxy["client-fingerprint"] = params["fp"]

        # SNI для обычного TLS
        elif params.get("sni"):
            proxy["servername"] = params["sni"]

        return proxy

    except Exception:
        return None

def generate_clash_yaml(proxies):
    """Генерирует минимальный рабочий Clash YAML"""
    names = [p["name"] for p in proxies]

    # Вручную строим YAML (без внешних библиотек)
    lines = []
    lines.append("mixed-port: 7890")
    lines.append("allow-lan: false")
    lines.append("mode: rule")
    lines.append("log-level: info")
    lines.append("external-controller: 127.0.0.1:9090")
    lines.append("")
    lines.append("dns:")
    lines.append("  enable: true")
    lines.append("  nameserver:")
    lines.append("    - 8.8.8.8")
    lines.append("    - 1.1.1.1")
    lines.append("")
    lines.append("proxies:")

    for p in proxies:
        lines.append(f"  - name: \"{p['name']}\"")
        lines.append(f"    type: {p['type']}")
        lines.append(f"    server: {p['server']}")
        lines.append(f"    port: {p['port']}")
        lines.append(f"    uuid: {p['uuid']}")
        lines.append(f"    tls: {str(p.get('tls', False)).lower()}")
        lines.append(f"    udp: true")
        lines.append(f"    skip-cert-verify: true")
        if p.get("flow"):
            lines.append(f"    flow: {p['flow']}")
        if p.get("network"):
            lines.append(f"    network: {p['network']}")
        if p.get("servername"):
            lines.append(f"    servername: {p['servername']}")
        if p.get("client-fingerprint"):
            lines.append(f"    client-fingerprint: {p['client-fingerprint']}")
        if p.get("reality-opts"):
            ro = p["reality-opts"]
            lines.append(f"    reality-opts:")
            lines.append(f"      public-key: {ro.get('public-key', '')}")
            lines.append(f"      short-id: {ro.get('short-id', '')}")
        if p.get("ws-opts"):
            wo = p["ws-opts"]
            lines.append(f"    ws-opts:")
            if wo.get("path"):
                lines.append(f"      path: \"{wo['path']}\"")
            if wo.get("headers"):
                lines.append(f"      headers:")
                for hk, hv in wo["headers"].items():
                    lines.append(f"        {hk}: {hv}")
        if p.get("grpc-opts"):
            lines.append(f"    grpc-opts:")
            lines.append(f"      grpc-service-name: {p['grpc-opts']['grpc-service-name']}")

    lines.append("")
    lines.append("proxy-groups:")
    lines.append("  - name: \"PROXY\"")
    lines.append("    type: select")
    lines.append("    proxies:")
    for n in names[:200]:  # FClash тормозит с тысячей узлов — берём первые 200
        lines.append(f"      - \"{n}\"")
    lines.append("")
    lines.append("  - name: \"Auto\"")
    lines.append("    type: url-test")
    lines.append("    url: http://www.gstatic.com/generate_204")
    lines.append("    interval: 300")
    lines.append("    proxies:")
    for n in names[:200]:
        lines.append(f"      - \"{n}\"")
    lines.append("")
    lines.append("rules:")
    lines.append("  - MATCH,PROXY")

    return "\n".join(lines)

def collect():
    unique_nodes = set()
    print("🚀 Старт сборки конфигов...\n")

    for name, url in SOURCES.items():
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            if res.status_code != 200:
                print(f"❌ [{name}] HTTP {res.status_code}")
                continue

            content = try_decode_base64(res.text)
            found = re.findall(r'vless://[^\s\r\n]+', content)
            print(f"✅ [{name}] найдено: {len(found)} узлов")
            unique_nodes.update(found)

        except Exception as e:
            print(f"⚠️ [{name}] ошибка: {e}")

    if not unique_nodes:
        print("\n⛔ Список пустой!")
        return

    node_list = sorted(unique_nodes)

    # --- Файл 1: sub.txt для Happ и v2ray-клиентов ---
    encoded = base64.b64encode("\n".join(node_list).encode('utf-8')).decode('utf-8')
    with open("sub.txt", "w") as f:
        f.write(encoded)

    # --- Файл 2: clash.yaml для FClash ---
    print("\n⚙️ Конвертация в Clash формат...")
    proxies = []
    for i, node in enumerate(node_list):
        proxy = parse_vless_to_clash(node, i)
        if proxy:
            proxies.append(proxy)

    # Убираем дубли по имени
    seen_names = set()
    unique_proxies = []
    for p in proxies:
        if p["name"] not in seen_names:
            seen_names.add(p["name"])
            unique_proxies.append(p)
        else:
            p["name"] = f"{p['name']}-{len(seen_names)}"
            seen_names.add(p["name"])
            unique_proxies.append(p)

    clash_content = generate_clash_yaml(unique_proxies)
    with open("clash.yaml", "w", encoding="utf-8") as f:
        f.write(clash_content)

    print(f"\n🎉 Готово!")
    print(f"   sub.txt  → {len(node_list)} узлов (для Happ)")
    print(f"   clash.yaml → {len(unique_proxies)} узлов (для FClash)")

if __name__ == "__main__":
    collect()
