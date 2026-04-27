import requests
import base64
import re

# Самые актуальные источники на данный момент
SOURCES = [
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/mix",
    "https://raw.githubusercontent.com/w1770946466/Auto_Proxy/main/Long_term_subscription_num",
    "https://raw.githubusercontent.com/stayman-mhm/V2Ray-Configs-Mirror/main/all.txt",
    "https://raw.githubusercontent.com/AikoH34/Free-Node/main/sub/mix",
    "https://raw.githubusercontent.com/vfarid/v2ray-share/main/all.txt"
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def decode_base64(text):
    try:
        text = text.strip().replace('\n', '').replace('\r', '')
        missing_padding = len(text) % 4
        if missing_padding:
            text += '=' * (4 - missing_padding)
        return base64.b64decode(text).decode('utf-8', errors='ignore')
    except:
        return text

def collect():
    unique_nodes = set()
    print("🚀 Запуск сбора конфигов...")
    
    for url in SOURCES:
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            if res.status_code != 200:
                print(f"❌ Ошибка {res.status_code} на источнике: {url}")
                continue
            
            content = res.text
            # Если контент похож на сплошной Base64 без протоколов, декодируем
            if "://" not in content[:150]:
                content = decode_base64(content)
                
            # Ищем все ссылки на конфиги
            found = re.findall(r'(?:vless|vmess|ss|trojan|shadowsocks)://[^\s]+', content)
            print(f"✅ {url} — найдено {len(found)} узлов")
            unique_nodes.update(found)
        except Exception as e:
            print(f"⚠️ Ошибка при чтении {url}: {e}")
    
    if not unique_nodes:
        print("⛔️ Критическая ошибка: Список пуст! Файл sub.txt не будет обновлен.")
        return

    # Собираем всё в кучу и пакуем обратно
    final_text = "\n".join(list(unique_nodes))
    encoded_final = base64.b64encode(final_text.encode('utf-8')).decode('utf-8')
    
    with open("sub.txt", "w") as f:
        f.write(encoded_final)
    
    print(f"🎉 Успех! Собрано всего {len(unique_nodes)} уникальных узлов.")

if __name__ == "__main__":
    collect()
