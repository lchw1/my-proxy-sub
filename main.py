import base64
import json
import re
import sys
import urllib.parse
from pathlib import Path

import requests


CONFIG_FILE = Path("sources.json")

DEFAULT_CONFIG = {
    "source_repos": [
        "https://github.com/igareck/vpn-configs-for-russia",
        "https://github.com/kort0881/vpn-vless-configs-russia",
        "https://github.com/yebekhe/TelegramV2rayCollector"
    ],
    "direct_urls": [],
    "sub_limit": 550,
    "clash_limit": 500,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

ALLOWED_EXTS = {".txt", ".sub", ".base64", ".b64", ".list"}
DISALLOWED_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".py", ".sh", ".md", ".rst", ".json", ".yml", ".yaml",
    ".toml", ".lock", ".ini", ".cfg", ".exe", ".bat"
}

NODE_RE = re.compile(r'(?:(?:vless|vmess|trojan|ss)://[^\s\r\n\'"<>]+)', re.IGNORECASE)


def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = DEFAULT_CONFIG.copy()
                cfg.update({k: v for k, v in data.items() if k in cfg})
                cfg["source_repos"] = [str(x).strip() for x in cfg.get("source_repos", []) if str(x).strip()]
                cfg["direct_urls"] = [str(x).strip() for x in cfg.get("direct_urls", []) if str(x).strip()]
                cfg["sub_limit"] = int(cfg.get("sub_limit", 550))
                cfg["clash_limit"] = int(cfg.get("clash_limit", 500))
                return cfg
        except Exception:
            pass

    CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    return DEFAULT_CONFIG.copy()


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
    head = text[:1200]
    if any(proto in head.lower() for proto in ("vless://", "vmess://", "trojan://", "ss://")):
        return text

    cleaned = "".join(text.split())
    if len(cleaned) < 32:
        return text

    try:
        cleaned += "=" * (-len(cleaned) % 4)
        decoded = base64.b64decode(cleaned).decode("utf-8", errors="ignore")
        if any(proto in decoded.lower() for proto in ("vless://", "vmess://", "trojan://", "ss://")):
            return decoded
    except Exception:
        pass

    return text


def github_owner_repo(repo_url: str):
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$", repo_url.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def is_probably_source_file(name: str) -> bool:
    lower = name.lower()
    ext = Path(lower).suffix

    if ext in DISALLOWED_EXTS:
        return False

    if ext in ALLOWED_EXTS:
        return True

    keywords = (
        "vless", "vmess", "trojan", "ss", "sub", "mix", "proxy",
        "node", "all", "base64", "filtered", "sni", "black", "white",
        "reality", "config", "collect", "mirror"
    )
    return any(k in lower for k in keywords)


def discover_github_files(repo_url: str, path: str = ""):
    owner, repo = github_owner_repo(repo_url)
    if not owner or not repo:
        return []

    api = f"https://api.github.com/repos/{owner}/{repo}/contents"
    if path:
        api += f"/{path.lstrip('/')}"

    data = fetch(api)
    if not data:
        return []

    try:
        items = json.loads(data)
    except Exception:
        return []

    if isinstance(items, dict):
        items = [items]

    found = []
    for item in items:
        item_type = item.get("type")
        if item_type == "dir":
            found.extend(discover_github_files(repo_url, item.get("path", "")))
        elif item_type == "file":
            name = item.get("name") or ""
            download_url = item.get("download_url")
            if download_url and is_probably_source_file(name):
                found.append(download_url)

    return found


def build_source_urls(cfg):
    urls = []
    seen = set()

    for repo in cfg["source_repos"]:
        print(f"SCAN {repo}")
        for u in discover_github_files(repo):
            if u not in seen:
                seen.add(u)
                urls.append(u)

    for u in cfg["direct_urls"]:
        if u not in seen:
            seen.add(u)
            urls.append(u)

    return urls


def clean_node(url: str) -> str:
    return url.strip().rstrip("),.;]}'\"")


def safe_name(raw: str, idx: int) -> str:
    raw = urllib.parse.unquote(raw or "")
    raw = raw.encode("ascii", errors="ignore").decode("ascii")
    raw = re.sub(r"[^a-zA-Z0-9 \-_.,()]+", "", raw).strip()
    return raw[:60] if len(raw) >= 2 else f"proxy-{idx}"


def parse_vless(url: str, idx: int):
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme.lower() != "vless" or not p.hostname or not p.port:
            return None

        params = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        sec = (params.get("security", ["none"])[0] or "none").lower()
        net = (params.get("type", ["tcp"])[0] or "tcp").lower()

        proxy = {
            "name": safe_name(p.fragment, idx),
            "type": "vless",
            "server": p.hostname,
            "port": int(p.port),
            "uuid": urllib.parse.unquote(p.username or ""),
            "tls": sec in ("tls", "reality"),
            "udp": True,
            "skip-cert-verify": True,
        }

        if net != "tcp":
            proxy["network"] = net

        if net == "ws":
            wo = {}
            if params.get("path", [""])[0]:
                wo["path"] = urllib.parse.unquote(params["path"][0])
            if params.get("host", [""])[0]:
                wo["headers"] = {"Host": params["host"][0]}
            if wo:
                proxy["ws-opts"] = wo
        elif net == "grpc":
            svc = urllib.parse.unquote(params.get("serviceName", [""])[0])
            if svc:
                proxy["grpc-opts"] = {"grpc-service-name": svc}

        if params.get("flow", [""])[0]:
            proxy["flow"] = params["flow"][0]
        if params.get("sni", [""])[0]:
            proxy["servername"] = params["sni"][0]
        if params.get("fp", [""])[0]:
            proxy["client-fingerprint"] = params["fp"][0]

        if sec == "reality":
            proxy["reality-opts"] = {
                "public-key": params.get("pbk", [""])[0],
                "short-id": params.get("sid", [""])[0],
            }

        return proxy
    except Exception:
        return None


def parse_trojan(url: str, idx: int):
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme.lower() != "trojan" or not p.hostname or not p.port:
            return None

        params = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        proxy = {
            "name": safe_name(p.fragment, idx),
            "type": "trojan",
            "server": p.hostname,
            "port": int(p.port),
            "password": urllib.parse.unquote(p.username or p.path.lstrip("/") or ""),
            "udp": True,
            "skip-cert-verify": True,
        }

        if params.get("sni", [""])[0]:
            proxy["servername"] = params["sni"][0]
        if params.get("fp", [""])[0]:
            proxy["client-fingerprint"] = params["fp"][0]
        if params.get("type", [""])[0] == "ws":
            proxy["network"] = "ws"
            wo = {}
            if params.get("path", [""])[0]:
                wo["path"] = urllib.parse.unquote(params["path"][0])
            if params.get("host", [""])[0]:
                wo["headers"] = {"Host": params["host"][0]}
            if wo:
                proxy["ws-opts"] = wo

        return proxy
    except Exception:
        return None


def parse_vmess(url: str, idx: int):
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme.lower() != "vmess":
            return None

        body = p.netloc + p.path
        fragment = p.fragment

        if "?" in body:
            body = body.split("?", 1)[0]

        body = body.strip()
        body += "=" * (-len(body) % 4)

        decoded = base64.urlsafe_b64decode(body.encode("utf-8", errors="ignore")).decode("utf-8", errors="ignore")
        info = json.loads(decoded)

        server = info.get("add") or info.get("server")
        port = info.get("port") or 443
        if not server:
            return None

        try:
            port = int(port)
        except Exception:
            port = 443

        proxy = {
            "name": safe_name(fragment or info.get("ps", ""), idx),
            "type": "vmess",
            "server": server,
            "port": port,
            "uuid": info.get("id", ""),
            "alterId": int(info.get("aid", 0) or 0),
            "cipher": info.get("cipher", "auto"),
            "udp": True,
            "skip-cert-verify": True,
        }

        if str(info.get("tls", "")).lower() in ("1", "true", "tls"):
            proxy["tls"] = True
        if info.get("sni"):
            proxy["servername"] = info["sni"]

        net = str(info.get("net", "tcp")).lower()
        if net != "tcp":
            proxy["network"] = net

        if net == "ws":
            wo = {}
            path = info.get("path")
            host = info.get("host")
            if path:
                wo["path"] = path
            if host:
                wo["headers"] = {"Host": host}
            if wo:
                proxy["ws-opts"] = wo
        elif net == "grpc":
            if info.get("path"):
                proxy["grpc-opts"] = {"grpc-service-name": info["path"]}

        return proxy
    except Exception:
        return None


def parse_ss(url: str, idx: int):
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme.lower() != "ss":
            return None

        if p.hostname and p.port and p.username:
            method = urllib.parse.unquote(p.username)
            password = urllib.parse.unquote(p.password or "")
            server = p.hostname
            port = int(p.port)

            return {
                "name": safe_name(p.fragment, idx),
                "type": "ss",
                "server": server,
                "port": port,
                "cipher": method,
                "password": password,
                "udp": True,
            }

        body = (p.netloc + p.path).split("?", 1)[0].strip()
        if "@" not in body:
            body += "=" * (-len(body) % 4)
            body = base64.urlsafe_b64decode(body.encode("utf-8", errors="ignore")).decode("utf-8", errors="ignore")

        if "@" not in body or ":" not in body:
            return None

        left, right = body.rsplit("@", 1)
        if ":" not in left or ":" not in right:
            return None

        method, password = left.split(":", 1)
        server, port = right.rsplit(":", 1)

        return {
            "name": safe_name(p.fragment, idx),
            "type": "ss",
            "server": server,
            "port": int(port),
            "cipher": method,
            "password": password,
            "udp": True,
        }
    except Exception:
        return None


def parse_node(url: str, idx: int):
    if url.startswith("vless://"):
        return parse_vless(url, idx)
    if url.startswith("trojan://"):
        return parse_trojan(url, idx)
    if url.startswith("vmess://"):
        return parse_vmess(url, idx)
    if url.startswith("ss://"):
        return parse_ss(url, idx)
    return None


def yaml_scalar(value):
    return json.dumps(value, ensure_ascii=False)


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
        out.append(f"  - name: {yaml_scalar(p['name'])}")
        out.append(f"    type: {p['type']}")
        out.append(f"    server: {yaml_scalar(p['server'])}")
        out.append(f"    port: {int(p['port'])}")

        if p["type"] == "vless":
            out.append(f"    uuid: {yaml_scalar(p['uuid'])}")
            out.append(f"    tls: {str(bool(p.get('tls'))).lower()}")
            out.append(f"    udp: {str(bool(p.get('udp', True))).lower()}")
            out.append(f"    skip-cert-verify: {str(bool(p.get('skip-cert-verify', True))).lower()}")
            if p.get("flow"):
                out.append(f"    flow: {yaml_scalar(p['flow'])}")
            if p.get("network"):
                out.append(f"    network: {yaml_scalar(p['network'])}")
            if p.get("client-fingerprint"):
                out.append(f"    client-fingerprint: {yaml_scalar(p['client-fingerprint'])}")
            if p.get("servername"):
                out.append(f"    servername: {yaml_scalar(p['servername'])}")
            if p.get("reality-opts"):
                ro = p["reality-opts"]
                out.append("    reality-opts:")
                out.append(f"      public-key: {yaml_scalar(ro.get('public-key', ''))}")
                out.append(f"      short-id: {yaml_scalar(ro.get('short-id', ''))}")
            if p.get("ws-opts"):
                wo = p["ws-opts"]
                out.append("    ws-opts:")
                if wo.get("path"):
                    out.append(f"      path: {yaml_scalar(wo['path'])}")
                if wo.get("headers"):
                    out.append("      headers:")
                    for k, v in wo["headers"].items():
                        out.append(f"        {k}: {yaml_scalar(v)}")
            if p.get("grpc-opts"):
                out.append("    grpc-opts:")
                out.append(f"      grpc-service-name: {yaml_scalar(p['grpc-opts'].get('grpc-service-name', ''))}")

        elif p["type"] == "trojan":
            out.append(f"    password: {yaml_scalar(p['password'])}")
            out.append(f"    udp: {str(bool(p.get('udp', True))).lower()}")
            out.append(f"    skip-cert-verify: {str(bool(p.get('skip-cert-verify', True))).lower()}")
            if p.get("servername"):
                out.append(f"    sni: {yaml_scalar(p['servername'])}")
            if p.get("client-fingerprint"):
                out.append(f"    client-fingerprint: {yaml_scalar(p['client-fingerprint'])}")
            if p.get("network"):
                out.append(f"    network: {yaml_scalar(p['network'])}")
            if p.get("ws-opts"):
                wo = p["ws-opts"]
                out.append("    ws-opts:")
                if wo.get("path"):
                    out.append(f"      path: {yaml_scalar(wo['path'])}")
                if wo.get("headers"):
                    out.append("      headers:")
                    for k, v in wo["headers"].items():
                        out.append(f"        {k}: {yaml_scalar(v)}")

        elif p["type"] == "vmess":
            out.append(f"    uuid: {yaml_scalar(p['uuid'])}")
            out.append(f"    alterId: {int(p.get('alterId', 0))}")
            out.append(f"    cipher: {yaml_scalar(p.get('cipher', 'auto'))}")
            out.append(f"    udp: {str(bool(p.get('udp', True))).lower()}")
            out.append(f"    skip-cert-verify: {str(bool(p.get('skip-cert-verify', True))).lower()}")
            if p.get("tls"):
                out.append("    tls: true")
            if p.get("servername"):
                out.append(f"    servername: {yaml_scalar(p['servername'])}")
            if p.get("network"):
                out.append(f"    network: {yaml_scalar(p['network'])}")
            if p.get("ws-opts"):
                wo = p["ws-opts"]
                out.append("    ws-opts:")
                if wo.get("path"):
                    out.append(f"      path: {yaml_scalar(wo['path'])}")
                if wo.get("headers"):
                    out.append("      headers:")
                    for k, v in wo["headers"].items():
                        out.append(f"        {k}: {yaml_scalar(v)}")
            if p.get("grpc-opts"):
                out.append("    grpc-opts:")
                out.append(f"      grpc-service-name: {yaml_scalar(p['grpc-opts'].get('grpc-service-name', ''))}")

        elif p["type"] == "ss":
            out.append(f"    cipher: {yaml_scalar(p['cipher'])}")
            out.append(f"    password: {yaml_scalar(p['password'])}")
            out.append(f"    udp: {str(bool(p.get('udp', True))).lower()}")

    out += [
        "",
        "proxy-groups:",
        f"  - name: {yaml_scalar('Auto')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:",
    ] + [f"      - {yaml_scalar(n)}" for n in top] + [
        "",
        f"  - name: {yaml_scalar('PROXY')}",
        "    type: select",
        "    proxies:",
        f"      - {yaml_scalar('Auto')}",
    ] + [f"      - {yaml_scalar(n)}" for n in top] + [
        "",
        "rules:",
        "  - MATCH,Auto",
    ]

    return "\n".join(out)


def main():
    cfg = load_config()

    if not cfg["source_repos"] and not cfg["direct_urls"]:
        print("CRITICAL: no sources configured.")
        sys.exit(1)

    print("=== Сбор ссылок на источники ===")
    source_urls = build_source_urls(cfg)
    print(f"FOUND SOURCES: {len(source_urls)}")

    print("=== Сбор узлов ===")
    ordered_nodes = []
    seen_nodes = set()

    for src in source_urls:
        raw = fetch(src)
        if not raw:
            continue

        text = decode_if_needed(raw)
        found = [clean_node(m) for m in NODE_RE.findall(text)]
        found = [n for n in found if n.startswith(("vless://", "vmess://", "trojan://", "ss://"))]

        if found:
            print(f"OK  {src.split('/')[-1]} — {len(found)} узлов")
        else:
            print(f"OK  {src.split('/')[-1]} — 0 узлов")

        for node in found:
            if node not in seen_nodes:
                seen_nodes.add(node)
                ordered_nodes.append(node)

    if not ordered_nodes:
        print("CRITICAL: 0 узлов!")
        sys.exit(1)

    print(f"\nВсего уникальных: {len(ordered_nodes)}")

    sub_nodes = ordered_nodes[: int(cfg["sub_limit"])]
    encoded = base64.b64encode("\n".join(sub_nodes).encode("utf-8")).decode("ascii")
    with open("sub.txt", "w", encoding="utf-8") as f:
        f.write(encoded)
    print(f"sub.txt записан ({len(sub_nodes)} узлов)")

    proxies = []
    seen_names = set()

    for idx, url in enumerate(ordered_nodes):
        p = parse_node(url, idx)
        if not p:
            continue

        base = p["name"]
        name = base
        c = 1
        while name in seen_names:
            name = f"{base}-{c}"
            c += 1
        p["name"] = name
        seen_names.add(name)
        proxies.append(p)

        if len(proxies) >= int(cfg["clash_limit"]):
            break

    with open("clash.yaml", "w", encoding="utf-8") as f:
        f.write(make_clash(proxies))
    print(f"clash.yaml записан ({len(proxies)} узлов)")


if __name__ == "__main__":
    main()
