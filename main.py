import requests
import base64
import re
import urllib.parse
import sys

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

# Источники без изменений
SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
    "https://raw.githubusercontent.com/kort0881/vpn-vless-configs-russia/main/githubmirror/clean/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/vless",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/mix",
]

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.text
    except:
        pass
    return ""

def decode_if_needed(text):
    if "vless://" in text[:500]:
        return text
    try:
        t = text.strip().replace('\n','').replace('\r','')
        t += '=' * (-len(t) % 4)
        return base64.b64decode(t).decode('utf-8', errors='ignore')
    except:
        return text

def safe_name(raw, idx):
    try:
        name = urllib.parse.unquote(raw)
    except:
        name = raw
    name = name.encode('ascii', errors='ignore').decode('ascii')
    name = re.sub(r'[^a-zA-Z0-9 \-_.,]', '', name).strip()
    return name[:60] if len(name) >= 2 else f"proxy-{idx}"

def parse_vless(url, idx):
    try:
        m = re.match(r'vless://([^@]+)@([^:]+):(\d+)\??([^#]*)#?(.*)', url)
        if not m: return None
        uuid, host, port, qs, raw_name = m.groups()
        params = {p.split('=')[0]: urllib.parse.unquote(p.split('=')[1]) for p in qs.split('&') if '=' in p}
        sec = params.get('security', 'none')
        proxy = {
            'name': safe_name(raw_name, idx),
            'type': 'vless', 'server': host, 'port': int(port), 'uuid': uuid,
            'tls': sec in ('tls', 'reality'), 'udp': True, 'skip-cert-verify': True,
        }
        net = params.get('type', 'tcp')
        if net == 'ws':
            proxy['network'] = 'ws'
            wo = {'path': urllib.parse.unquote(params.get('path', '/'))}
            if params.get('host'): wo['headers'] = {'Host': params['host']}
            proxy['ws-opts'] = wo
        elif net == 'grpc':
            proxy['network'] = 'grpc'
            proxy['grpc-opts'] = {'grpc-service-name': urllib.parse.unquote(params.get('serviceName', ''))}
        if params.get('flow'): proxy['flow'] = params['flow']
        if params.get('sni'): proxy['servername'] = params['sni']
        if params.get('fp'): proxy['client-fingerprint'] = params['fp']
        if sec == 'reality':
            proxy['reality-opts'] = {'public-key': params.get('pbk', ''), 'short-id': params.get('sid', '')}
        return proxy
    except:
        return None

def make_clash(proxies):
    names = [p['name'] for p in proxies]
    out = [
        "mixed-port: 7890", "allow-lan: false", "mode: global", "log-level: info",
        "dns: {enable: true, nameserver: ['8.8.8.8', '1.1.1.1']}", "", "proxies:"
    ]
    for p in proxies:
        out.append(f"  - name: \"{p['name']}\"\n    type: vless\n    server: {p['server']}\n    port: {p['port']}\n    uuid: {p['uuid']}\n    tls: {str(p['tls']).lower()}\n    udp: true\n    skip-cert-verify: true")
        for key in ('flow', 'network', 'client-fingerprint'):
            if p.get(key): out.append(f"    {key}: {p[key]}")
        if p.get('servername'): out.append(f"    servername: \"{p['servername']}\"")
        if p.get('reality-opts'):
            ro = p['reality-opts']
            out.append(f"    reality-opts:\n      public-key: {ro['public-key']}\n      short-id: \"{ro['short-id']}\"")
        if p.get('ws-opts'):
            wo = p['ws-opts']
            out.append(f"    ws-opts:\n      path: \"{wo['path']}\"")
            if wo.get('headers'):
                out.append("      headers:")
                for k, v in wo['headers'].items(): out.append(f"        {k}: \"{v}\"")
        if p.get('grpc-opts'):
            out.append(f"    grpc-opts:\n      grpc-service-name: \"{p['grpc-opts']['grpc-service-name']}\"")
            
    out += ["", "proxy-groups:", f"  - name: \"Auto\"\n    type: url-test\n    url: http://www.gstatic.com/generate_204\n    interval: 180\n    proxies:"]
    out += [f"      - \"{n}\"" for n in names]
    out += ["", f"  - name: \"PROXY\"\n    type: select\n    proxies:\n      - \"Auto\""]
    out += [f"      - \"{n}\"" for n in names]
    out += ["", "rules:", "  - MATCH,Auto"]
    return "\n".join(out)

def main():
    nodes = set()
    print("=== Сбор узлов ===")
    for url in SOURCES:
        raw = fetch(url)
        if not raw: continue
        text = decode_if_needed(raw)
        found = re.findall(r'vless://[^\s\r\n]+', text)
        nodes.update(found)
        
    # Берем ТОЛЬКО первые 550 узлов для всего
    final_nodes = sorted(list(nodes))[:550]
    print(f"Отобрано для работы: {len(final_nodes)} узлов")
    
    # 1. Записываем sub.txt (Happ)
    encoded = base64.b64encode('\n'.join(final_nodes).encode()).decode()
    with open('sub.txt', 'w') as f:
        f.write(encoded)
    print("sub.txt готов.")
    
    # 2. Записываем clash.yaml (FClash)
    proxies, seen = [], set()
    for i, url in enumerate(final_nodes):
        p = parse_vless(url, i)
        if not p: continue
        base = p['name']
        name, c = base, 1
        while name in seen:
            name = f"{base}-{c}"; c += 1
        p['name'] = name
        seen.add(name)
        proxies.append(p)
        
    with open('clash.yaml', 'w', encoding='utf-8') as f:
        f.write(make_clash(proxies))
    print("clash.yaml готов.")

if __name__ == '__main__':
    main()
