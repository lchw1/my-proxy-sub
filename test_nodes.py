import random
import shutil
import subprocess
from pathlib import Path

RAW_FILE = Path("raw.txt")
OUT_FILE = Path("tested.txt")

CHUNK_SIZE = 100
TOTAL_LIMIT = 800
RUN_TIMEOUT = 180
THREADS = 20
MDELAY = 2500


def load_nodes(path: Path) -> list[str]:
    if not path.exists():
        return []
    nodes = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("vless://"):
            nodes.append(line)
    return nodes


def chunked(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def read_alive(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    seen = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("vless://") and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def run_xray_knife(input_file: Path, output_file: Path) -> bool:
    exe = shutil.which("xray-knife") or "./xray-knife"
    cmd = [
        exe, "http",
        "-f", str(input_file),
        "--thread", str(THREADS),
        "--mdelay", str(MDELAY),
        "--insecure",
        "--type", "txt",
        "-o", str(output_file),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
        if proc.returncode != 0:
            print(f"rc={proc.returncode}")
            if proc.stdout:
                print(proc.stdout[-800:])
            if proc.stderr:
                print(proc.stderr[-800:])
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT: {input_file.name}")
        return False
    except Exception as e:
        print(f"ERR: {e}")
        return False


def main():
    nodes = load_nodes(RAW_FILE)
    if not nodes:
        print("raw.txt пуст")
        OUT_FILE.write_text("", encoding="utf-8")
        return

    random.Random(42).shuffle(nodes)
    nodes = nodes[:TOTAL_LIMIT]
    print(f"Тестируем {len(nodes)} кандидатов")

    tmp_dir = Path("chunks")
    tmp_dir.mkdir(exist_ok=True)

    alive_all = []
    seen = set()

    for idx, part in enumerate(chunked(nodes, CHUNK_SIZE), start=1):
        chunk_in = tmp_dir / f"chunk_{idx:04d}.txt"
        chunk_out = tmp_dir / f"chunk_{idx:04d}_out.txt"
        chunk_in.write_text("\n".join(part), encoding="utf-8")

        print(f"[{idx}] size={len(part)}")
        ok = run_xray_knife(chunk_in, chunk_out)
        if not ok:
            continue

        alive = read_alive(chunk_out)
        print(f"    alive={len(alive)}")
        for node in alive:
            if node not in seen:
                seen.add(node)
                alive_all.append(node)

    OUT_FILE.write_text("\n".join(alive_all), encoding="utf-8")
    print(f"Готово: {len(alive_all)} -> {OUT_FILE}")


if __name__ == "__main__":
    main()
