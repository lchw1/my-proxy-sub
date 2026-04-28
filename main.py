import requests
import base64
import re
import urllib.parse
import sys

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

# Все источники — прямые проверенные ссылки, без API
SOURCES = [
    # === igareck (проверены на РФ каждые 2 часа) ===
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
    # === kort0881 (1000+ узлов, обновление каждые 15 минут) ===
    "https://raw.githubusercontent.com/kort0881/vpn-vless-configs-russia/main/githubmirror/clean/vless.txt",
    # === yebekhe (крупный международный агрегатор) ===
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/vless",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/mix",
]

# ─────────────────────────────────────────────
def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.text
        print(f"  SKIP {url.split('/')[-1]} — HTTP {r.status_code}")
    except Exception as e:
        print(f"  ERR  {url.split('/')[-1]} — {e}")
    return ""

def decode_if_needed(text):
    if "vless://" in text[:500]:
        return text
    try:
        t = text.strip().replace('\n','').replace('\r','')
        t += '=' * (-len(t) % 4)
        return base64.b64decode(t).decode('utf-8', errors='ignore')
    except Exception:
        return text

def safe_name(raw, idx):
    try:
        name = urllib.parse.unquote(raw)
    except Exception:
        name = raw
    name = name.encode('ascii', errors='ignore').decode('ascii')
    name = re.sub(r'[^a-zA-Z0-9 \-_.,]', '', name).strip()
    return name[:60] if len(name) >= 2 else f"proxy-{idx}"

def parse_vless(url, idx):
    try:
        m = re.match(r'vless://([^@]+)@([^:]+):(\d+)\??([^#]*)#?(.*)', url)
        if not m:
            return None
        uuid, host, port, qs, raw_name = m.groups()

        params = {}
        for p in qs.split('&'):
            if '=' in p:
                k, v = p.split('=', 1)
                params[k] = urllib.parse.unquote(v)

        sec = params.get('security', 'none')
        proxy = {
            'name':            safe_name(raw_name, idx),
            'type':            'vless',
            'server':          host,
            'port':            int(port),
            'uuid':            uuid,
            'tls':             sec in ('tls', 'reality'),
            'udp':             True,
            'skip-cert-verify': True,
        }

        net = params.get('type', 'tcp')
        if net == 'ws':
            proxy['network'] = 'ws'
            wo = {}
            if params.get('path'):
                wo['path'] = urllib.parse.unquote(params['path'])
            if params.get('host'):
                wo['headers'] = {'Host': params['host']}
            if wo:
                proxy['ws-opts'] = wo
        elif net == 'grpc':
            proxy['network'] = 'grpc'
            svc = urllib.parse.unquote(params.get('serviceName', ''))
            if svc:
                proxy['grpc-opts'] = {'grpc-service-name': svc}

        if params.get('flow'):
            proxy['flow'] = params['flow']
        if params.get('sni'):
            proxy['servername'] = params['sni']
        if params.get('fp'):
            proxy['client-fingerprint'] = params['fp']
        if sec == 'reality':
            proxy['reality-opts'] = {
                'public-key': params.get('pbk', ''),
                'short-id':   params.get('sid', ''),
            }
        return proxy
    except Exception:
        return None

def q(s):
    return '"' + str(s).replace('\\','\\\\').replace('"','\\"') + '"'

def make_clash(proxies):
    names = [p['name'] for p in proxies]
    out = [
        "mixed-port: 7890",
        "allow-lan: false",
        "mode: global",       # Глобальный режим по умолчанию!
        "log-level: info",
        "external-controller: 127.0.0.1:9090",
        "",
        "dns:",
        "  enable: true",
        "  nameserver: [8.8.8.8, 1.1.1.1]",
        "",
        "proxies:",
    ]

    for p in proxies:
        out.append(f"  - name: {q(p['name'])}")
        out.append(f"    type: vless")
        out.append(f"    server: {p['server']}")
        out.append(f"    port: {p['port']}")
        out.append(f"    uuid: {p['uuid']}")
        out.append(f"    tls: {str(p['tls']).lower()}")
        out.append(f"    udp: true")
        out.append(f"    skip-cert-verify: true")
        for key in ('flow', 'network', 'client-fingerprint'):
            if p.get(key):
                out.append(f"    {key}: {p[key]}")
        if p.get('servername'):
            out.append(f"    servername: {q(p['servername'])}")
        if p.get('reality-opts'):
            ro = p['reality-opts']
            out.append(f"    reality-opts:")
            out.append(f"      public-key: {ro['public-key']}")
            out.append(f"      short-id: {q(ro['short-id'])}")
        if p.get('ws-opts'):
            wo = p['ws-opts']
            out.append(f"    ws-opts:")
            if wo.get('path'):
                out.append(f"      path: {q(wo['path'])}")
            if wo.get('headers'):
                out.append(f"      headers:")
                for k, v in wo['headers'].items():
                    out.append(f"        {k}: {q(v)}")
        if p.get('grpc-opts'):
            out.append(f"    grpc-opts:")
            out.append(f"      grpc-service-name: {q(p['grpc-opts']['grpc-service-name'])}")

    top200 = names[:200]
    out += [
        "",
        "proxy-groups:",
        f"  - name: {q('Auto')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:",
    ] + [f"      - {q(n)}" for n in top200] + [
        "",
        f"  - name: {q('PROXY')}",
        "    type: select",
        "    proxies:",
        f"      - {q('Auto')}",
    ] + [f"      - {q(n)}" for n in top200] + [
        "",
        "rules:",
        "  - MATCH,Auto",   # По умолчанию Auto (лучший пинг)
    ]
    return "\n".join(out)

# ─────────────────────────────────────────────
def main():
    nodes = set()
    print("=== Сбор узлов ===")
    for url in SOURCES:
        name = url.split('/')[-1]
        raw = fetch(url)
        if not raw:
            continue
        text = decode_if_needed(raw)
        found = re.findall(r'vless://[^\s\r\n]+', text)
        print(f"  OK   {name} — {len(found)} узлов")
        nodes.update(found)

    if not nodes:
        print("CRITICAL: 0 узлов! Прерываем.")
        sys.exit(1)   # Роняем Action с ошибкой — сразу видно в логах

    node_list = sorted(nodes)
    print(f"\nВсего уникальных: {len(node_list)}")

    # sub.txt
    encoded = base64.b64encode('\n'.join(node_list).encode()).decode()
    with open('sub.txt', 'w') as f:
        f.write(encoded)
    print(f"sub.txt записан ({len(node_list)} узлов)")

    # clash.yaml
    proxies, seen = [], set()
    for i, url in enumerate(node_list):
        p = parse_vless(url, i)
        if not p:
            continue
        base = p['name']
        name, c = base, 1
        while name in seen:
            name = f"{base}-{c}"; c += 1
        p['name'] = name
        seen.add(name)
        proxies.append(p)

    with open('clash.yaml', 'w', encoding='utf-8') as f:
        f.write(make_clash(proxies))
    print(f"clash.yaml записан ({len(proxies)} узлов)")

if __name__ == '__main__':
    main()
