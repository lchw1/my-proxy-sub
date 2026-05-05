import asyncio
import random
import shutil
import subprocess
from pathlib import Path

RAW_FILE = Path("raw.txt")
OUT_FILE = Path("tested.txt")

# Настройка под GitHub Actions:
CHUNK_SIZE = 250          # маленькие пачки = меньше шанс зависнуть
RUN_TIMEOUT = 240         # секунд на одну пачку
TOTAL_LIMIT = 1200        # общий лимит тестируемых кандидатов за один прогон
THREADS = 40
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
            print(f"xray-knife rc={proc.returncode}")
            if proc.stdout:
                print(proc.stdout[-1000:])
            if proc.stderr:
                print(proc.stderr[-1000:])
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT: {input_file.name}")
        return False
    except Exception as e:
        print(f"ERR: {e}")
        return False


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


def main():
    nodes = load_nodes(RAW_FILE)
    if not nodes:
        print("raw.txt пуст")
        OUT_FILE.write_text("", encoding="utf-8")
        return

    # Перемешиваем, чтобы не было эффекта "всё хорошее в начале / всё плохое в конце"
    random.Random(42).shuffle(nodes)

    # Жёсткий лимит, чтобы job не умер на 50k
    nodes = nodes[:TOTAL_LIMIT]
    print(f"Тестируем {len(nodes)} кандидатов из raw.txt")

    tmp_dir = Path("chunks")
    tmp_dir.mkdir(exist_ok=True)

    all_alive = []
    seen_alive = set()

    for idx, part in enumerate(chunked(nodes, CHUNK_SIZE), start=1):
        chunk_in = tmp_dir / f"chunk_{idx:04d}.txt"
        chunk_out = tmp_dir / f"chunk_{idx:04d}_out.txt"

        chunk_in.write_text("\n".join(part), encoding="utf-8")
        print(f"[{idx}] chunk size={len(part)}")

        ok = run_xray_knife(chunk_in, chunk_out)
        if not ok:
            continue

        alive = read_alive(chunk_out)
        print(f"    alive={len(alive)}")
        for node in alive:
            if node not in seen_alive:
                seen_alive.add(node)
                all_alive.append(node)

    OUT_FILE.write_text("\n".join(all_alive), encoding="utf-8")
    print(f"Готово: {len(all_alive)} живых нод -> {OUT_FILE}")


if __name__ == "__main__":
    main()
