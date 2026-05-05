import base64
import re
import urllib.parse
from pathlib import Path

TESTED_FILE = Path("tested.txt")
SUB_FILE = Path("sub.txt")
CLASH_FILE = Path("clash.yaml")

VLESS_RE = re.compile(r"^vless://[^\s]+$", re.IGNORECASE)


def parse_vless(uri: str) -> dict | None:
    uri = uri.strip()
    if not VLESS_RE.match(uri):
        return None

    try:
        u = urllib.parse.urlsplit(uri)
        if u.scheme.lower() != "vless":
            return None

        uuid = urllib.parse.unquote(u.username or "")
        server = u.hostname or ""
        port = u.port or 443
        fragment = urllib.parse.unquote(u.fragment or "")
        q = urllib.parse.parse_qs(u.query)

        sec = q.get("security", [""])[0].lower()
        net = q.get("type", ["tcp"])[0].lower()
        sni = q.get("sni", [""])[0]
        host = q.get("host", [""])[0]
        path = q.get("path", [""])[0]
        fp = q.get("fp", ["chrome"])[0].lower()
        flow = q.get("flow", [""])[0]
        pbk = q.get("pbk", [""])[0]
        sid = q.get("sid", [""])[0]
        service_name = q.get("serviceName", [""])[0]

        if not uuid or not server:
            return None

        name = fragment or f"{server}:{port}"

        return {
            "name": name,
            "uuid": uuid,
            "server": server,
            "port": int(port),
            "sec": sec,
            "net": net,
            "sni": sni,
            "host": host,
            "path": path,
            "fp": fp,
            "flow": flow,
            "pbk": pbk,
            "sid": sid,
            "service_name": service_name,
            "raw": uri,
        }
    except Exception:
        return None


def yaml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_proxy(p: dict) -> str:
    lines = []
    lines.append(f'  - name: "{yaml_escape(p["name"])}"')
    lines.append("    type: vless")
    lines.append(f'    server: "{yaml_escape(p["server"])}"')
    lines.append(f"    port: {p['port']}")
    lines.append(f'    uuid: "{yaml_escape(p["uuid"])}"')
    lines.append("    udp: true")

    # TLS / Reality
    if p["sec"] in ("tls", "reality"):
        lines.append("    tls: true")
        if p["sni"] or p["server"]:
            lines.append(f'    servername: "{yaml_escape(p["sni"] or p["server"])}"')
        lines.append(f'    client-fingerprint: "{yaml_escape(p["fp"] or "chrome")}"')
        lines.append("    skip-cert-verify: true")

    if p["flow"]:
        lines.append(f'    flow: "{yaml_escape(p["flow"])}"')

    if p["sec"] == "reality":
        # Reality-specific fields
        if p["pbk"]:
            lines.append("    reality-opts:")
            lines.append(f'      public-key: "{yaml_escape(p["pbk"])}"')
            if p["sid"]:
                lines.append(f'      short-id: "{yaml_escape(p["sid"])}"')
        # some clients behave better with explicit packet encoding
        lines.append("    packet-encoding: xudp")

    # transport
    if p["net"] == "ws":
        lines.append("    network: ws")
        lines.append("    ws-opts:")
        if p["path"]:
            lines.append(f'      path: "{yaml_escape(p["path"])}"')
        else:
            lines.append('      path: "/"')
        if p["host"]:
            lines.append("      headers:")
            lines.append(f'        Host: "{yaml_escape(p["host"])}"')

    elif p["net"] == "grpc":
        lines.append("    network: grpc")
        lines.append("    grpc-opts:")
        if p["service_name"]:
            lines.append(f'      grpc-service-name: "{yaml_escape(p["service_name"])}"')
        else:
            lines.append('      grpc-service-name: ""')

    else:
        lines.append("    network: tcp")

    return "\n".join(lines)


def main():
    if not TESTED_FILE.exists():
        print("tested.txt not found")
        SUB_FILE.write_text("", encoding="utf-8")
        CLASH_FILE.write_text("", encoding="utf-8")
        return

    raw_lines = []
    for line in TESTED_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("vless://"):
            raw_lines.append(line)

    # dedupe, preserving order
    seen = set()
    nodes = []
    for uri in raw_lines:
        if uri not in seen:
            seen.add(uri)
            nodes.append(uri)

    parsed = []
    for uri in nodes:
        p = parse_vless(uri)
        if p:
            parsed.append(p)

    print(f"tested.txt: {len(parsed)} рабочих нод")

    # sub.txt as base64 subscription
    sub_text = "\n".join([p["raw"] for p in parsed]).encode("utf-8")
    sub_b64 = base64.b64encode(sub_text).decode("utf-8")
    SUB_FILE.write_text(sub_b64, encoding="utf-8")

    # Clash Meta config
    out = []
    out.append("port: 7890")
    out.append("socks-port: 7891")
    out.append("allow-lan: true")
    out.append("mode: rule")
    out.append("log-level: info")
    out.append("ipv6: false")
    out.append("")
    out.append("dns:")
    out.append("  enable: true")
    out.append("  enhanced-mode: fake-ip")
    out.append("  nameserver:")
    out.append("    - 1.1.1.1")
    out.append("    - 8.8.8.8")
    out.append("")
    out.append("proxies:")
    for p in parsed:
        out.append(render_proxy(p))
    out.append("")
    out.append("proxy-groups:")
    out.append('  - name: "AUTO"')
    out.append("    type: url-test")
    out.append("    use:")
    out.append('      - "PROXIES"')
    out.append("    url: http://www.gstatic.com/generate_204")
    out.append("    interval: 300")
    out.append("    tolerance: 50")
    out.append("")
    out.append('  - name: "PROXIES"')
    out.append("    type: select")
    out.append("    proxies:")
    for p in parsed:
        out.append(f'      - "{yaml_escape(p["name"])}"')
    out.append('      - "DIRECT"')
    out.append("")
    out.append("rules:")
    out.append("  - MATCH,PROXIES")

    CLASH_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"sub.txt — {len(parsed)} нод")
    print(f"clash.yaml — {len(parsed)} нод")
    print("Готово!")


if __name__ == "__main__":
    main()
