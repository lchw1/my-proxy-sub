"""
Читает tested.txt от xray-knife (рабочие ноды),
строит sub.txt и clash.yaml.
Если tested.txt пустой — берёт raw.txt как fallback.
"""

import base64
import json
import re
import sys
import urllib.parse
from pathlib import Path

SUB_LIMIT   = 500
CLASH_LIMIT = 450

NODE_RE = re.compile(r"vless://[^\s\r\n'\"<>]+", re.IGNORECASE)


def load_nodes() -> list:
    # Пробуем tested.txt (результат xray-knife)
    tested = Path("tested.txt")
    if tested.exists():
        nodes = [
            u.strip()
            for u in NODE_RE.findall(tested.read_text(encoding="utf-8", errors="ignore"))
            if u.startswith("vless://")
        ]
        if nodes:
            print(f"tested.txt: {len(nodes)} рабочих нод")
            return nodes
        print("tested.txt пустой — fallback на raw.txt")

    # Fallback — берём raw.txt
    raw = Path("raw.txt")
    if raw.exists():
        nodes = [
            u.strip()
            for u in NODE_RE.findall(raw.read_text(encoding="utf-8", errors="ignore"))
            if u.startswith("vless://")
        ]
        print(f"raw.txt fallback: {len(nodes)} нод")
        return nodes

    print("CRITICAL: нет ни tested.txt ни raw.txt!")
    sys.exit(1)


# ---------------------------------------------------------------------------
# VLESS → Clash
# ---------------------------------------------------------------------------

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
        q = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        sec = (q.get("security", ["none"])[0] or "none").lower()
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

        net = (q.get("type", ["tcp"])[0] or "tcp").lower()
        if net != "tcp":
            proxy["network"] = net
        if flow := q.get("flow", [""])[0]:
            proxy["flow"] = flow
        if sni := q.get("sni", [""])[0]:
            proxy["servername"] = sni
        if fp := q.get("fp", [""])[0]:
            proxy["client-fingerprint"] = fp
        pe = q.get("packet-encoding", [""])[0] or q.get("packetEncoding", [""])[0]
        if pe:
            proxy["packet-encoding"] = pe

        if net == "ws":
            wo: dict = {}
            if path := urllib.parse.unquote(q.get("path", [""])[0]):
                wo["path"] = path
            host = q.get("host", [""])[0]
            if host:
                wo["headers"] = {"Host": host}
            else:
                # WS без заголовка Host — практически всегда нерабочий
                return None
            proxy["ws-opts"] = wo
        elif net == "grpc":
            gn = urllib.parse.unquote(q.get("serviceName", [""])[0])
            if gn:
                proxy["grpc-opts"] = {"grpc-service-name": gn}

        if sec == "reality":
            proxy["reality-opts"] = {
                "public-key": q.get("pbk", [""])[0],
                "short-id": q.get("sid", [""])[0],
            }
        return proxy
    except Exception:
        return None


def j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def make_clash(proxies: list) -> str:
    names = [p["name"] for p in proxies]
    top = names[:150]

    out = [
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
        "  fallback:",
        "    - tls://8.8.8.8:853",
        "    - tls://1.1.1.1:853",
        "",
        "proxies:",
    ]

    for p in proxies:
        out += [
            f"  - name: {j(p['name'])}",
            "    type: vless",
            f"    server: {j(p['server'])}",
            f"    port: {int(p['port'])}",
            f"    uuid: {j(p['uuid'])}",
            f"    tls: {str(p.get('tls', True)).lower()}",
            f"    udp: {str(p.get('udp', True)).lower()}",
            f"    skip-cert-verify: {str(p.get('skip-cert-verify', True)).lower()}",
        ]
        for key in ("flow", "network", "client-fingerprint", "servername", "packet-encoding"):
            if p.get(key):
                out.append(f"    {key}: {j(p[key])}")
        if ro := p.get("reality-opts"):
            out += [
                "    reality-opts:",
                f"      public-key: {j(ro.get('public-key', ''))}",
                f"      short-id: {j(ro.get('short-id', ''))}",
            ]
        if wo := p.get("ws-opts"):
            out.append("    ws-opts:")
            if wo.get("path"):
                out.append(f"      path: {j(wo['path'])}")
            if wo.get("headers"):
                out.append("      headers:")
                for k, v in wo["headers"].items():
                    out.append(f"        {k}: {j(v)}")
        if go := p.get("grpc-opts"):
            out += [
                "    grpc-opts:",
                f"      grpc-service-name: {j(go.get('grpc-service-name', ''))}",
            ]

    out += [
        "",
        "proxy-groups:",
        f"  - name: {j('Auto')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:",
    ] + [f"      - {j(n)}" for n in top] + [
        "",
        f"  - name: {j('PROXY')}",
        "    type: select",
        "    proxies:",
        f"      - {j('Auto')}",
    ] + [f"      - {j(n)}" for n in top] + [
        "",
        "rules:",
        "  - GEOIP,RU,DIRECT",
        "  - DOMAIN-SUFFIX,ru,DIRECT",
        "  - DOMAIN-SUFFIX,рф,DIRECT",
        "  - DOMAIN-SUFFIX,yandex.ru,DIRECT",
        "  - DOMAIN-SUFFIX,vk.com,DIRECT",
        "  - DOMAIN-SUFFIX,mail.ru,DIRECT",
        "  - DOMAIN-SUFFIX,sberbank.ru,DIRECT",
        "  - DOMAIN-SUFFIX,tinkoff.ru,DIRECT",
        "  - DOMAIN-SUFFIX,gosuslugi.ru,DIRECT",
        "  - MATCH,Auto",
    ]
    return "\n".join(out)


def main():
    nodes = load_nodes()
    if not nodes:
        print("CRITICAL: 0 нод!")
        sys.exit(1)

    # sub.txt
    sub = nodes[:SUB_LIMIT]
    encoded = base64.b64encode("\n".join(sub).encode()).decode("ascii")
    Path("sub.txt").write_text(encoded, encoding="utf-8")
    print(f"sub.txt — {len(sub)} нод")

    # clash.yaml
    proxies: list = []
    seen_names: set = set()
    for idx, url in enumerate(nodes):
        p = parse_vless(url, idx)
        if not p:
            continue
        name, c, base = p["name"], 1, p["name"]
        while name in seen_names:
            name = f"{base}-{c}"
            c += 1
        p["name"] = name
        seen_names.add(name)
        proxies.append(p)
        if len(proxies) >= CLASH_LIMIT:
            break

    if not proxies:
        print("CRITICAL: 0 TLS/Reality прокси!")
        sys.exit(1)

    Path("clash.yaml").write_text(make_clash(proxies), encoding="utf-8")
    print(f"clash.yaml — {len(proxies)} нод")
    print("Готово!")


if __name__ == "__main__":
    main()
