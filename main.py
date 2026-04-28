import requests
import base64
import re
import urllib.parse
import sys

# Список источников (скрипт сам обходит их)
SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
    "https://raw.githubusercontent.com/kort0881/vpn-vless-configs-russia/main/githubmirror/clean/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/vless"
]

def fetch_and_decode(url):
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200: return ""
        content = r.text
        # Если контент похож на base64 (нет vless:// в начале), декодируем
        if "vless://" not in content[:100]:
            try:
                content = base64.b64decode(content.strip()).decode('utf-8', errors='ignore')
            except: pass
        return content
    except:
        return ""

def safe_yaml_name(raw, idx):
    # Самая жесткая очистка: только латиница и цифры. 
    # Это 100% убирает ошибку "found character that cannot start any token"
    try:
        decoded = urllib.parse.unquote(raw)
    except:
        decoded = raw
    clean = re.sub(r'[^a-zA-Z0-9]', '', decoded)
    return f"Node{idx}{clean[:10]}"

def parse_vless(url, idx):
    try:
        # Регулярка для разбора vless
        pattern = r'vless://([^@]+)@([^:]+):(\d+)\??([^#]*)#?(.*)'
        match = re.match(pattern, url)
        if not match: return None
        
        uuid, host, port, query, raw_name = match.groups()
        params = {p.split('=')[0]: urllib.parse.unquote(p.split('=')[1]) for p in query.split('&') if '=' in p}
        
        return {
            'name': safe_yaml_name(raw_name, idx),
            'server': host,
            'port': int(port),
            'uuid': uuid,
            'tls': params.get('security') in ['tls', 'reality'],
            'sni': params.get('sni', ''),
            'net': params.get('type', 'tcp'),
            'path': params.get('path', '/'),
            'pbk': params.get('pbk', ''),
            'sid': params.get('sid', '')
        }
    except:
        return None

def main():
    print("--- Запуск автоматического сбора узлов ---")
    all_links = set()
    
    for url in SOURCES:
        print(f"Сканирую: {url}")
        content = fetch_and_decode(url)
        links = re.findall(r'vless://[^\s\r\n]+', content)
        all_vless = [l for l in links if 'vless://' in l]
        all_links.update(all_vless)
        
    # Лимит 550 уникальных узлов
    final_links = sorted(list(all_links))[:550]
    print(f"Отобрано: {len(final_links)} уникальных узлов")

    # 1. Создаем sub.txt (Happ)
    with open('sub.txt', 'w', encoding='utf-8') as f:
        encoded = base64.b64encode('\n'.join(final_links).encode()).decode()
        f.write(encoded)
    print("Файл sub.txt готов.")

    # 2. Создаем clash.yaml (FClash)
    proxies = []
    for i, link in enumerate(final_links):
        p = parse_vless(link, i)
        if p: proxies.append(p)

    with open('clash.yaml', 'w', encoding='utf-8') as f:
        # Базовые настройки
        f.write("mixed-port: 7890\nallow-lan: false\nmode: global\nlog-level: info\n")
        f.write("dns:\n  enable: true\n  nameserver:\n    - 8.8.8.8\n    - 1.1.1.1\n")
        f.write("proxies:\n")
        
        # Список прокси
        for p in proxies:
            f.write(f"  - name: \"{p['name']}\"\n")
            f.write(f"    type: vless\n")
            f.write(f"    server: {p['server']}\n")
            f.write(f"    port: {p['port']}\n")
            f.write(f"    uuid: {p['uuid']}\n")
            f.write(f"    tls: {str(p['tls']).lower()}\n")
            f.write(f"    udp: true\n")
            f.write(f"    skip-cert-verify: true\n")
            if p['sni']: f.write(f"    servername: \"{p['sni']}\"\n")
            if p['net'] == 'ws':
                f.write(f"    network: ws\n")
                f.write(f"    ws-opts:\n      path: \"{p['path']}\"\n")
            if p['pbk']:
                f.write(f"    reality-opts:\n")
                f.write(f"      public-key: {p['pbk']}\n")
                f.write(f"      short-id: \"{p['sid']}\"\n")

        # Группы выбора
        f.write("\nproxy-groups:\n")
        f.write("  - name: \"Auto\"\n    type: url-test\n    url: http://www.gstatic.com/generate_204\n    interval: 180\n    proxies:\n")
        for p in proxies:
            f.write(f"      - \"{p['name']}\"\n")
        
        f.write("\nrules:\n  - MATCH,Auto\n")
    
    print("Файл clash.yaml готов. Ошибок нет.")

if __name__ == "__main__":
    main()
