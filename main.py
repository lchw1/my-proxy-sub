import base64
import json
import re
import socket
import sys
import urllib.parse
from pathlib import Path

import requests

CONFIG_FILE = Path("sources.json")

DEFAULT_CONFIG = {
    "source_repos": [
        "https://github.com/igareck/vpn-configs-for-russia",
        "https://github.com/kort0881/vpn-vless-configs-russia",
        "https://github.com/yebekhe/TelegramV2rayCollector",
    ],
    "direct_urls": [],
    "sub_limit": 550,
    "clash_limit": 500,
    "tcp_timeout": 1.5,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

ALLOWED_EXTS = {".txt", ".sub", ".base64", ".b64", ".list"}
SKIP_NAME_PARTS = {
    "readme", "license", "changelog", "requirements", "setup",
    "example", "sample", "test", "demo", "package-lock", "pyproject",
}

NODE_RE = re.compile(r"vless://[^\s\r\n'\"<>]+", re.IGNORECASE)


def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = DEFAULT_CONFIG.copy()
                for key in ("source_repos", "direct_urls", "sub_limit", "clash_limit", "tcp_timeout"):
                    if key in data:
                        cfg[key] = data[key]

                cfg["source_repos"] = [
                    str(x).strip() for x in cfg.get("source_repos", []) if str(x).strip()
                ]
                cfg["direct_urls"] = [
                    str(x).strip() for x in cfg.get("direct_urls", []) if str(x).strip()
                ]
                cfg["sub_limit"] = int(cfg.get("sub_limit", 550))
                cfg["clash_limit"] = int(cfg.get("clash_limit", 500))
                cfg["tcp_timeout"] = float(cfg.get("tcp_timeout", 1.5))
                return cfg
        except Exception:
            pass

    CONFIG_FILE.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return DEFAULT_CONFIG.copy()


def fetch_text(url: str, timeout: int = 25) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
        print(f"SKIP {url} — HTTP {r.status_code}")
    except Exception as e:
        print(f"ERR  {url} — {e}")
    return ""


def fetch_json(url: str, timeout: int = 25):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        print(f"SKIP {url} — HTTP {r.status_code}")
    except Exception as e:
        print(f"ERR  {url} — {e}")
    return None


def github_owner_repo(repo_url: str):
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$", repo_url.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def is_probably_source_file(path: str) -> bool:
    lower = path.lower()
    name = Path(lower).name
    ext = Path(name).suffix

    if ext not in ALLOWED_EXTS:
        return False

    if any(part in lower for part in SKIP_NAME_PARTS):
        return False

    return True


def raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    safe_path = urllib.parse.quote(path, safe="/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{safe_path}"


def discover_github_files(repo_url: str):
    owner, repo = github_owner_repo(repo_url)
    if not owner or not repo:
        return []

    info = fetch_json(f"https://api.github.com/repos/{owner}/{repo}")
    if not isinstance(info, dict):
        return []

    branch = info.get("default_branch") or "main"
    tree = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")

    urls = []
    if isinstance(tree, dict) and isinstance(tree.get("tree"), list):
        for item in tree["tree"]:
            if item.get("type") != "blob":
                continue
            path = item.get("path") or ""
            if is_probably_source_file(path):
                urls.append(raw_url(owner, repo, branch, path))
        return urls

    return discover_github_files_contents(owner, repo, "", branch)


def discover_github_files_contents(owner: str, repo: str, path: str = "", branch: str = "main"):
    api = f"https://api.github.com/repos/{owner}/{repo}/contents"
    if path:
        api += f"/{path.lstrip('/')}"
    api += f"?ref={urllib.parse.quote(branch)}"

    data = fetch_json(api)
    if not data:
        return []

    if isinstance(data, dict):
        data = [data]

    found = []
    for item in data:
        item_type = item.get("type")
        if item_type == "dir":
            found.extend(discover_github_files_contents(owner, repo, item.get("path", ""), branch))
        elif item_type == "file":
            path = item.get("path") or ""
            dl = item.get("download_url")
            if dl and is_probably_source_file(path):
                found.append(dl)

    return found


def build_source_urls(cfg):
    urls = []
    seen = set()

    for repo in cfg["source_repos"]:
        print(f"SCAN {repo}")
        try:
            for u in discover_github_files(repo):
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
        except Exception as e:
            print(f"ERR  discover {repo} — {e}")

    for u in cfg["direct_urls"]:
        if u not in seen:
            seen.add(u)
            urls.append(u)

    return urls


def decode_if_needed(text: str) -> str:
    if "vless://" in text[:1200].lower():
        return text

    cleaned = "".join(text.split())
    if len(cleaned) < 32:
        return text

    try:
        cleaned += "=" * (-len(cleaned) % 4)
        decoded = base64.b64decode(cleaned).decode("utf-8", errors="ignore")
        if "vless://" in decoded.lower():
            return decoded
    except Exception:
        pass

    return text


def clean_node(url: str) -> str:
    return url.strip().rstrip("),.;]}'\"")


def safe_name(raw: str, idx: int) -> str:
    raw = urllib.parse.unquote(raw or "")
    raw = raw.encode("ascii", errors="ignore").decode("ascii")
    raw = re.sub(r"[^a-zA-Z0-9 \-_.(),]+", "", raw).strip()
    return raw[:60] if len(raw) >= 2 else f"proxy-{idx}"


def parse_vless(url: str, idx: int):
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme.lower() != "vless" or not p.hostname or not p.port:
            return None

        params = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        sec = (params.get("security", ["none"])[0] or "none").lower()

        # Оставляем только TLS / Reality
        if sec not in ("tls", "reality"):
            return None

        proxy = {
            "name": safe_name(p.fragment, idx),
            "type": "vless",
            "server": p.hostname,
            "port": int(p.port),
            "uuid": urllib.parse.unquote(p.username or ""),
            "tls": True,
            "udp": True,
            "skip-cert-verify": True,
        }

        net = (params.get("type", ["tcp"])[0] or "tcp").lower()
        if net != "tcp":
            proxy["network"] = net

        flow = params.get("flow", [""])[0]
        if flow:
            proxy["flow"] = flow

        sni = params.get("sni", [""])[0]
        if sni:
            proxy["servername"] = sni

        fp = params.get("fp", [""])[0]
        if fp:
            proxy["client-fingerprint"] = fp

        packet_encoding = params.get("packet-encoding", [""])[0] or params.get("packetEncoding", [""])[0]
        if packet_encoding:
            proxy["packet-encoding"] = packet_encoding

        if net == "ws":
            ws_opts = {}
            path = params.get("path", [""])[0]
            host = params.get("host", [""])[0]
            if path:
                ws_opts["path"] = urllib.parse.unquote(path)
            if host:
                ws_opts["headers"] = {"Host": host}
            if ws_opts:
                proxy["ws-opts"] = ws_opts

        elif net == "grpc":
            grpc_name = urllib.parse.unquote(params.get("serviceName", [""])[0])
            if grpc_name:
                proxy["grpc-opts"] = {"grpc-service-name": grpc_name}

        if sec == "reality":
            proxy["reality-opts"] = {
                "public-key": params.get("pbk", [""])[0],
                "short-id": params.get("sid", [""])[0],
            }

        return proxy
    except Exception:
        return None


def parse_node(url: str, idx: int):
    if url.startswith("vless://"):
        return parse_vless(url, idx)
    return None


def is_alive(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


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
        out.append("    type: vless")
        out.append(f"    server: {yaml_scalar(p['server'])}")
        out.append(f"    port: {int(p['port'])}")
        out.append(f"    uuid: {yaml_scalar(p['uuid'])}")
        out.append(f"    tls: {str(bool(p.get('tls', True))).lower()}")
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
        if p.get("packet-encoding"):
            out.append(f"    packet-encoding: {yaml_scalar(p['packet-encoding'])}")

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

    sub_limit = int(cfg["sub_limit"])
    clash_limit = int(cfg["clash_limit"])
    tcp_timeout = float(cfg["tcp_timeout"])

    collection_target = max(sub_limit, clash_limit) + 300

    print("=== Сбор VLESS узлов ===")
    ordered_nodes = []
    seen_nodes = set()

    for src in source_urls:
        if len(ordered_nodes) >= collection_target:
            break

        raw = fetch_text(src)
        if not raw:
            continue

        text = decode_if_needed(raw)
        found = [clean_node(m) for m in NODE_RE.findall(text)]
        found = [n for n in found if n.startswith("vless://")]

        if found:
            print(f"OK  {src.split('/')[-1]} — {len(found)} vless")
        else:
            print(f"OK  {src.split('/')[-1]} — 0 vless")

        for node in found:
            if node not in seen_nodes:
                seen_nodes.add(node)
                ordered_nodes.append(node)

            if len(ordered_nodes) >= collection_target:
                break

    if not ordered_nodes:
        print("CRITICAL: 0 nodes!")
        sys.exit(1)

    print(f"\nВсего уникальных VLESS: {len(ordered_nodes)}")

    # sub.txt — короткий
    sub_nodes = ordered_nodes[:sub_limit]
    encoded = base64.b64encode("\n".join(sub_nodes).encode("utf-8")).decode("ascii")
    with open("sub.txt", "w", encoding="utf-8") as f:
        f.write(encoded)
    print(f"sub.txt записан ({len(sub_nodes)} узлов)")

    # clash.yaml — только успешные, живые, без дублей по server:port
    proxies = []
    seen_names = set()
    seen_servers = set()

    for idx, url in enumerate(ordered_nodes):
        p = parse_node(url, idx)
        if not p:
            continue

        key = (p["server"], p["port"])
        if key in seen_servers:
            continue

        if not is_alive(p["server"], p["port"], timeout=tcp_timeout):
            continue

        seen_servers.add(key)

        base = p["name"]
        name = base
        c = 1
        while name in seen_names:
            name = f"{base}-{c}"
            c += 1

        p["name"] = name
        seen_names.add(name)
        proxies.append(p)

        if len(proxies) >= clash_limit:
            break

    if not proxies:
        print("CRITICAL: 0 proxies for clash!")
        sys.exit(1)

    with open("clash.yaml", "w", encoding="utf-8") as f:
        f.write(make_clash(proxies))

    print(f"clash.yaml записан ({len(proxies)} узлов)")


if __name__ == "__main__":
    main()
