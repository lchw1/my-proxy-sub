import requests
import base64
import re

# Источники (можно добавлять свои)
SOURCES = [
    "https://raw.githubusercontent.com/freev2ray/v2ray-free-nodes/master/v2ray",
    "https://raw.githubusercontent.com/mahdavipanah/free-v2ray-configs/master/all.txt",
    "https://raw.githubusercontent.com/vfarid/v2ray-share/main/all.txt"
]

def decode_base64(text):
    try:
        # Убираем пробелы и восстанавливаем паддинг (знаки =) для правильной расшифровки
        text = text.strip()
        missing_padding = len(text) % 4
        if missing_padding:
            text += '=' * (4 - missing_padding)
        return base64.b64decode(text).decode('utf-8', errors='ignore')
    except:
        return ""

def collect():
    unique_nodes = set()
    
    for url in SOURCES:
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                continue
            
            content = res.text
            # Если в тексте нет ://, значит он скорее всего закодирован в Base64
            if "://" not in content:
                content = decode_base64(content)
                
            # Ищем все протоколы
            found = re.findall(r'(?:vless|vmess|ss|trojan)://[^\s]+', content)
            unique_nodes.update(found)
        except Exception as e:
            print(f"Ошибка при парсинге {url}: {e}")
            continue
    
    # Собираем всё в список и кодируем обратно в Base64 для Clash/V2RAY
    combined = "\n".join(list(unique_nodes))
    encoded = base64.b64encode(combined.encode('utf-8')).decode('utf-8')
    
    with open("sub.txt", "w") as f:
        f.write(encoded)
    
    print(f"Успешно собрано узлов: {len(unique_nodes)}")

if __name__ == "__main__":
    collect()
