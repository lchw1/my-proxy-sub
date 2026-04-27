import requests
import base64
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

# ===== ИСТОЧНИКИ =====
# igareck/vpn-configs-for-russia — живые тесты на сервере в РФ каждые 2 часа
# Все файлы содержат только VLESS

SOURCES = {
    # --- ЧЁРНЫЕ СПИСКИ (обычный домашний интернет) ---
    "🏴 ЧС полный (ПК)":         "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "🏴 ЧС мобильный (телефон)": "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",

    # --- БЕЛЫЕ СПИСКИ (мобильный интернет с ограничениями операторов) ---
    "⚪ БС CIDR полный (ПК)":    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_CIDR_RUS.txt",
    "⚪ БС CIDR мобильный":      "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_CIDR_RUS_mobile.txt",
    "⚪ БС SNI":                  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_SNI_RUS.txt",

    # --- Дополнительные агрегаторы ---
    "🌐 Yebekhe VLESS":          "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/vless",
}

def collect():
    unique_nodes = set()
    print("🚀 Старт сборки конфигов...\n")

    for name, url in SOURCES.items():
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            if res.status_code != 200:
                print(f"❌ [{name}] HTTP {res.status_code}")
                continue

            content = res.text

            # Декодируем Base64 если нет явных ссылок vless://
            if "vless://" not in content[:300]:
                try:
                    text = content.strip().replace('\n', '').replace('\r', '')
                    pad = len(text) % 4
                    if pad:
                        text += '=' * (4 - pad)
                    content = base64.b64decode(text).decode('utf-8', errors='ignore')
                except Exception:
                    pass  # Оставляем как есть если декодирование не нужно

            # Берём только VLESS
            found = re.findall(r'vless://[^\s\r\n]+', content)
            print(f"✅ [{name}] найдено: {len(found)} VLESS узлов")
            unique_nodes.update(found)

        except Exception as e:
            print(f"⚠️ [{name}] ошибка: {e}")

    if not unique_nodes:
        print("\n⛔ Список пустой! sub.txt не обновлён.")
        return

    final_text = "\n".join(sorted(unique_nodes))
    encoded = base64.b64encode(final_text.encode('utf-8')).decode('utf-8')

    with open("sub.txt", "w") as f:
        f.write(encoded)

    print(f"\n🎉 Готово! Уникальных VLESS узлов: {len(unique_nodes)}")

if __name__ == "__main__":
    collect()
