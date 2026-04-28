import requests
import base64
import re
import urllib.parse

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

# ============================================================
# СТАТИЧНЫЕ источники (стабильные, редко меняют структуру)
# ============================================================
STATIC_SOURCES = [
    # kort0881 — 1200+ узлов, обновляется каждые 15 минут
    "https://raw.githubusercontent.com/kort0881/vpn-vless-configs-russia/main/githubmirror/clean/vless.txt",
    # igareck — дополнительные файлы из подпапок (API их не видит)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
]

# ============================================================
# ДИНАМИЧЕСКИЙ источник — igareck (сам находит все .txt файлы)
# ============================================================
IGARECK_REPO = "igareck/vpn-configs-for-russia"

def get_igareck_sources():
    """Через GitHub API находит все VLESS .txt файлы в репозитории igareck"""
    url = f"https://api.github.com/repos/{IGARECK_REPO}/contents/"
    sources = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"⚠️ GitHub API недоступен: HTTP {res.status_code}")
            return sources
        files = res.json()
        for f in files:
            name = f.get("name", "")
            # Берём только .txt файлы с VLESS в названии
            if name.endswith(".txt") and "VLESS" in name.upper():
                sources.append(f["download_url"])
                print(f"  📄 Найден файл: {name}")
    except Exception as e:
        print(f"⚠️ Ошибка GitHub API: {e}")
    return sources

# ============================================================
# Утилиты
# ============================================================
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

def clean_proxy_name(raw_name, index):
    try:
        name = urllib.parse.unquote(raw_name)
    except Exception:
        name = raw_name
    name = name.encode('ascii', errors='ignore').decode('ascii')
    name = re.sub(r'[^a-zA-Z0-9 \-_.,]', '', name).strip()
    if not name or len(name) < 2:
        name = f"proxy-{index}"
    return name[:80]

def parse_vless_to_clash(vless_url, index):
    try:
        match = re.match(r'vless://([^@]+)@([^:]+):(\d+)\??([^#]*)#?(.*)', vless_url)
        if not match:
            return None
        uuid, host, port, params_str, raw_name = match.groups()
        port = int(port)
        params = {}
        if params_str:
            for p in params_str.split('&'):
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = urllib.parse.unquote(v)

        proxy_name = clean_proxy_name(raw_name, index)
        security = params.get("security", "none")
        is_tls = security in ("tls", "reality")

        proxy = {
            "name": proxy_name,
            "type": "vless",
            "server": host,
            "port": port,
            "uuid": uuid,
            "tls": is_tls,
            "udp": True,
            "skip-cert-verify": True,
        }

        network = params.get("type", "tcp")
        if network == "ws":
            proxy["network"] = "ws"
            ws_opts = {}
            path = params.get("path", "")
            ws_host = params.get("host", "")
            if path:
                ws_opts["path"] = urllib.parse.unquote(path)
            if ws_host:
                ws_opts["headers"] = {"Host": ws_host}
            if ws_opts:
                proxy["ws-opts"] = ws_opts
            if params.get("sni"):
                proxy["servername"] = params["sni"]
        elif network == "grpc":
            proxy["network"] = "grpc"
            svc = params.get("serviceName", "")
            if svc:
                proxy["grpc-opts"] = {"grpc-service-name": urllib.parse.unquote(svc)}

        if params.get("flow"):
            proxy["flow"] = params["flow"]

        if security == "reality":
            proxy["reality-opts"] = {
                "public-key": params.get("pbk", ""),
                "short-id": params.get("sid", ""),
            }
            if params.get("sni"):
                proxy["servername"] = params["sni"]
            if params.get("fp"):
                proxy["client-fingerprint"] = params["fp"]
        elif params.get("sni"):
            proxy["servername"] = params["sni"]

        return proxy
    except Exception:
        return None

def yaml_str(val):
    val = str(val).replace('\\', '\\\\').replace('"', '\\"')
    return f'"{val}"'

def generate_clash_yaml(proxies):
    names = [p["name"] for p in proxies]
    lines = [
        "mixed-port: 7890",
        "allow-lan: false",
        "mode: rule",
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
        lines.append(f"  - name: {yaml_str(p['name'])}")
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
            lines.append(f"    servername: {yaml_str(p['servername'])}")
        if p.get("client-fingerprint"):
            lines.append(f"    client-fingerprint: {p['client-fingerprint']}")
        if p.get("reality-opts"):
            ro = p["reality-opts"]
            lines.append(f"    reality-opts:")
            lines.append(f"      public-key: {ro.get('public-key', '')}")
            lines.append(f"      short-id: {yaml_str(ro.get('short-id', ''))}")
        if p.get("ws-opts"):
            wo = p["ws-opts"]
            lines.append(f"    ws-opts:")
            if wo.get("path"):
                lines.append(f"      path: {yaml_str(wo['path'])}")
            if wo.get("headers"):
                lines.append(f"      headers:")
                for hk, hv in wo["headers"].items():
                    lines.append(f"        {hk}: {yaml_str(hv)}")
        if p.get("grpc-opts"):
            lines.append(f"    grpc-opts:")
            lines.append(f"      grpc-service-name: {yaml_str(p['grpc-opts']['grpc-service-name'])}")

    lines += [
        "",
        "proxy-groups:",
        f"  - name: {yaml_str('PROXY')}",
        "    type: select",
        "    proxies:",
    ]
    for n in names[:200]:
        lines.append(f"      - {yaml_str(n)}")

    lines += [
        "",
        f"  - name: {yaml_str('Auto')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 300",
        "    proxies:",
    ]
    for n in names[:200]:
        lines.append(f"      - {yaml_str(n)}")

    lines += ["", "rules:", "  - MATCH,PROXY"]
    return "\n".join(lines)

# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================
def collect():
    unique_nodes = set()
    print("🚀 Старт сборки...\n")

    # 1. Динамически находим все файлы у igareck
    print("🔍 Ищем файлы у igareck через GitHub API...")
    dynamic_sources = get_igareck_sources()
    print(f"  Найдено {len(dynamic_sources)} файлов\n")

    # 2. Объединяем все источники
    all_sources = dynamic_sources + STATIC_SOURCES

    # 3. Качаем и парсим
    for url in all_sources:
        name = url.split("/")[-1]
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            if res.status_code != 200:
                print(f"❌ [{name}] HTTP {res.status_code}")
                continue
            content = try_decode_base64(res.text)
            found = re.findall(r'vless://[^\s\r\n]+', content)
            print(f"✅ [{name}] {len(found)} узлов")
            unique_nodes.update(found)
        except Exception as e:
            print(f"⚠️ [{name}] ошибка: {e}")

    if not unique_nodes:
        print("\n⛔ Список пустой! Файлы не обновлены.")
        return

    node_list = sorted(unique_nodes)

    # sub.txt для Happ
    encoded = base64.b64encode("\n".join(node_list).encode('utf-8')).decode('utf-8')
    with open("sub.txt", "w") as f:
        f.write(encoded)

    # clash.yaml для FClash
    proxies = []
    seen_names = set()
    for i, node in enumerate(node_list):
        proxy = parse_vless_to_clash(node, i)
        if not proxy:
            continue
        base = proxy["name"]
        name = base
        counter = 1
        while name in seen_names:
            name = f"{base}-{counter}"
            counter += 1
        proxy["name"] = name
        seen_names.add(name)
        proxies.append(proxy)

    clash_content = generate_clash_yaml(proxies)
    with open("clash.yaml", "w", encoding="utf-8") as f:
        f.write(clash_content)

    print(f"\n🎉 Готово!")
    print(f"   sub.txt   → {len(node_list)} узлов (Happ)")
    print(f"   clash.yaml → {len(proxies)} узлов (FClash)")

if __name__ == "__main__":
    collect()
