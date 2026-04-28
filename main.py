import base64
import json
import re
import sys
import urllib.parse
from pathlib import Path

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# Только репозитории, а не отдельные файлы
SOURCE_REPOS = [
    "https://github.com/igareck/vpn-configs-for-russia",
    "https://github.com/kort0881/vpn-vless-configs-russia",
    "https://github.com/yebekhe/TelegramV2rayCollector",
]

# Дополнительно можно держать прямые ссылки, если очень надо
DIRECT_URLS = []

CACHE_FILE = Path("sources_cache.json")


def fetch(url: str, timeout: int = 20) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
        print(f"SKIP {url} — HTTP {r.status_code}")
    except Exception as e:
        print(f"ERR  {url} — {e}")
    return ""


def decode_if_needed(text: str) -> str:
    if "vless://" in text[:1000] or "vmess://" in text[:1000] or "trojan://" in text[:1000]:
        return text
    try:
        t = text.strip().replace("\n", "").replace("\r", "")
        t += "=" * (-len(t) % 4)
        decoded = base64.b64decode(t).decode("utf-8", errors="ignore")
        return decoded if decoded else text
    except Exception:
        return text


def github_owner_repo(repo_url: str):
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def discover_github_files(repo_url: str, path: str = ""):
    """
    Рекурсивно находит файлы в GitHub repo через Contents API.
    Возвращает raw download_url для подходящих файлов.
    """
    owner, repo = github_owner_repo(repo_url)
    if not owner or not repo:
        return []

    api = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}".rstrip("/")
    data = fetch(api)
    if not data:
        return []

    try:
        items = json.loads(data)
    except Exception:
        return []

    found = []

    # Если API вернул один файл, а не список
    if isinstance(items, dict):
        items = [items]

    for item in items:
        if item.get("type") == "dir":
            sub_path = item.get("path", "")
            found.extend(discover_github_files(repo_url, sub_path))
            continue

        if item.get("type") != "file":
            continue

        name = (item.get("name") or "").lower()
        download_url = item.get("download_url")

        if not download_url:
            continue

        # Подхватываем только вероятные базы
        if (
            name.endswith(".txt")
            or name.endswith(".sub")
            or name.endswith(".base64")
            or "vless" in name
            or "mix" in name
            or "sub" in name
            or "proxy" in name
        ):
            found.append(download_url)

    return found


def load_sources():
    sources = []

    # Пытаемся загрузить кэш, чтобы не зависеть от временных проблем GitHub API
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                sources.extend(cached)
        except Exception:
            pass

    # Автообновление из репозиториев
    for repo in SOURCE_REPOS:
        print(f"SCAN {repo}")
        sources.extend(discover_github_files(repo))

    # Ручные прямые ссылки, если добавишь
    sources.extend(DIRECT_URLS)

    # Убираем дубликаты
    deduped = []
    seen = set()
    for s in sources:
        if s not in seen:
            seen.add(s)
            deduped.append(s)

    # Обновляем кэш
    try:
        CACHE_FILE.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return deduped


def safe_name(raw, idx):
    try:
        name = urllib.parse.unquote(raw)
    except Exception:
        name = raw
    name = name.encode("ascii", errors="ignore").decode("ascii")
    name = re.sub(r"[^a-zA-Z0-9 \-_.,]", "", name).strip()
    return name[:60] if len(name) >= 2 else f"proxy-{idx}"


def parse_vless(url, idx):
    try:
        m = re.match(r"vless://([^@]+)@([^:]+):(\d+)\??([^#]*)#?(.*)", url)
        if not m:
            return None

        uuid, host, port, qs, raw_name = m.groups()

        params = {}
        for p in qs.split("&"):
            if "=" in p:
                k, v = p.split("=", 1)
                params[k] = urllib.parse.unquote(v)

        sec = params.get("security", "none")
        proxy = {
            "name": safe_name(raw_name, idx),
            "type": "vless",
            "server": host,
            "port": int(port),
            "uuid": uuid,
            "tls": sec in ("tls", "reality"),
            "udp": True,
            "skip-cert-verify": True,
        }

        net = params.get("type", "tcp")
        if net == "ws":
            proxy["network"] = "ws"
            wo = {}
            if params.get("path"):
                wo["path"] = urllib.parse.unquote(params["path"])
            if params.get("host"):
                wo["headers"] = {"Host": params["host"]}
            if wo:
                proxy["ws-opts"] = wo
        elif net == "grpc":
            proxy["network"] = "grpc"
            svc = urllib.parse.unquote(params.get("serviceName", ""))
            if svc:
                proxy["grpc-opts"] = {"grpc-service-name": svc}

        if params.get("flow"):
            proxy["flow"] = params["flow"]
        if params.get("sni"):
            proxy["servername"] = params["sni"]
        if params.get("fp"):
            proxy["client-fingerprint"] = params["fp"]

        if sec == "reality":
            proxy["reality-opts"] = {
                "public-key": params.get("pbk", ""),
                "short-id": params.get("sid", ""),
            }

        return proxy
    except Exception:
        return None


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def make_clash(proxies):
    names = [p["name"] for p in proxies]
    top = names[:150]

    out = [
        "mixed-port: 7890",
        "allow-lan: false",
        "mode: global",
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
        out.append(f"  - name: {q(p['name'])}")
        out.append("    type: vless")
        out.append(f"    server: {p['server']}")
        out.append(f"    port: {p['port']}")
        out.append(f"    uuid: {p['uuid']}")
        out.append(f"    tls: {str(p['tls']).lower()}")
        out.append("    udp: true")
        out.append("    skip-cert-verify: true")

        if p.get("flow"):
            out.append(f"    flow: {q(p['flow'])}")
        if p.get("network"):
            out.append(f"    network: {q(p['network'])}")
        if p.get("client-fingerprint"):
            out.append(f"    client-fingerprint: {q(p['client-fingerprint'])}")
        if p.get("servername"):
            out.append(f"    servername: {q(p['servername'])}")

        if p.get("reality-opts"):
            ro = p["reality-opts"]
            out.append("    reality-opts:")
            out.append(f"      public-key: {q(ro['public-key'])}")
            out.append(f"      short-id: {q(ro['short-id'])}")

        if p.get("ws-opts"):
            wo = p["ws-opts"]
            out.append("    ws-opts:")
            if wo.get("path"):
                out.append(f"      path: {q(wo['path'])}")
            if wo.get("headers"):
                out.append("      headers:")
                for k, v in wo["headers"].items():
                    out.append(f"        {k}: {q(v)}")

        if p.get("grpc-opts"):
            out.append("    grpc-opts:")
            out.append(f"      grpc-service-name: {q(p['grpc-opts']['grpc-service-name'])}")

    out += [
        "",
        "proxy-groups:",
        f"  - name: {q('Auto')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:",
    ] + [f"      - {q(n)}" for n in top] + [
        "",
        f"  - name: {q('PROXY')}",
        "    type: select",
        "    proxies:",
        f"      - {q('Auto')}",
    ] + [f"      - {q(n)}" for n in top] + [
        "",
        "rules:",
        "  - MATCH,Auto",
    ]

    return "\n".join(out)


def main():
    sources = load_sources()
    print(f"FOUND SOURCES: {len(sources)}")

    nodes = set()

    print("=== Сбор узлов ===")
    for url in sources:
        raw = fetch(url)
        if not raw:
            continue

        text = decode_if_needed(raw)
        found = re.findall(r'(?:vless|vmess|trojan|ss)://[^\s\r\n]+', text)
        print(f"OK  {url.split('/')[-1]} — {len(found)} узлов")
        nodes.update(found)

    if not nodes:
        print("CRITICAL: 0 узлов!")
        sys.exit(1)

    node_list = sorted(nodes)
    print(f"\nВсего уникальных: {len(node_list)}")

    # sub.txt — полный список
    encoded = base64.b64encode("\n".join(node_list).encode()).decode()
    with open("sub.txt", "w", encoding="utf-8") as f:
        f.write(encoded)
    print(f"sub.txt записан ({len(node_list)} узлов)")

    # clash.yaml — облегчённый
    proxies, seen = [], set()
    for i, url in enumerate(node_list[:500]):
        p = parse_vless(url, i)
        if not p:
            continue

        base = p["name"]
        name, c = base, 1
        while name in seen:
            name = f"{base}-{c}"
            c += 1
        p["name"] = name
        seen.add(name)
        proxies.append(p)

    with open("clash.yaml", "w", encoding="utf-8") as f:
        f.write(make_clash(proxies))

    print(f"clash.yaml записан ({len(proxies)} узлов)")


if __name__ == "__main__":
    main()
