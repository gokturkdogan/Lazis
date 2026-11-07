#!/usr/bin/env python3
"""Short, stoppable resource measurement for LAZIS (Phase 15B). Read-only: it looks at processes,
memory and swap, and at the numbers the app logs when started with LAZIS_METRICS=1.

  python3 scripts/measure-resources.py --seconds 120 --label m2 [--unload-on-stop]
  python3 scripts/measure-resources.py --report-log ~/Library/Logs/LAZIS/dev

Start it BEFORE the app: WebKit processes that appear after it starts are counted as LAZIS's.
It stops early (and, with --unload-on-stop, asks Ollama to unload the model; no setting is
changed) when free memory falls below 20 % or swap grows by more than 512 MB from the start.
It never closes other apps.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

FREE_MIN = 20
SWAP_MAX_GROWTH_MB = 512


def mem() -> tuple[int, float]:
    swap = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True).stdout
    free = subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True).stdout
    used = re.search(r"used = ([\d.]+)M", swap)
    pct = re.search(r"(\d+)%", free)
    return (int(pct.group(1)) if pct else 100), (float(used.group(1)) if used else 0.0)


def role(cmd: str, pid: int, before: set[int]) -> str | None:
    if "lazis-desktop" in cmd or "/LAZIS.app/Contents/MacOS/" in cmd:
        return "shell"
    if "-m lazis serve" in cmd:
        return "backend"
    if "lazis.providers.web.helper" in cmd:
        return "net_helper"
    if "whisper-server" in cmd:
        return "whisper"
    if "WebKit." in cmd and pid not in before:
        return "webkit_gpu" if "GPU" in cmd else "webkit_net" if "Networking" in cmd else "webkit_content"
    if "ollama" in cmd and "runner" in cmd:
        return "ollama_runner"
    if "ollama serve" in cmd:
        return "ollama_serve"
    return None


def processes() -> list[tuple[int, float, int, str]]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,%cpu=,rss=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            rows.append((int(parts[0]), float(parts[1]), int(parts[2]), parts[3]))
    return rows


def stats(xs: list[float]) -> dict[str, float]:
    return {"n": len(xs), "mean": round(statistics.mean(xs), 1), "median": round(statistics.median(xs), 1),
            "worst": round(max(xs), 1)} if xs else {"n": 0}  # fmt: skip


def unload_model() -> None:
    try:
        tags = json.loads(urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5).read())
        for m in tags.get("models", []):
            body = json.dumps({"model": m["name"], "keep_alive": 0}).encode()
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body), timeout=30)
            print(f"unloaded {m['name']}")
    except Exception as exc:  # noqa: BLE001 - best effort, reported
        print(f"could not unload the model: {exc}")


def sample(seconds: int, label: str, unload: bool) -> dict[str, object]:
    before = {pid for pid, _, _, cmd in processes() if "WebKit." in cmd}
    free0, swap0 = mem()
    print(f"[{label}] start free={free0}% swap={swap0:.0f}M; start the app now", flush=True)
    per: dict[str, dict[str, list[float]]] = {}
    totals_cpu: list[float] = []
    totals_mem: list[float] = []
    lowest_free, highest_swap = free0, swap0
    stopped = None
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        free, swap = mem()
        lowest_free, highest_swap = min(lowest_free, free), max(highest_swap, swap)
        if free < FREE_MIN or swap - swap0 > SWAP_MAX_GROWTH_MB:
            stopped = f"free={free}% swap+{swap - swap0:.0f}M"
            print(f"STOP: {stopped}", flush=True)
            if unload:
                unload_model()
            break
        cpu_total = mem_total = 0.0
        for pid, cpu, rss, cmd in processes():
            r = role(cmd, pid, before)
            if r is None:
                continue
            d = per.setdefault(r, {"cpu": [], "rss": []})
            d["cpu"].append(cpu)
            d["rss"].append(rss / 1024)
            if not r.startswith("ollama"):
                cpu_total += cpu
                mem_total += rss / 1024
        totals_cpu.append(cpu_total)
        totals_mem.append(mem_total)
        time.sleep(2)
    return {
        "label": label,
        "stopped": stopped,
        "start": {"free_pct": free0, "swap_mb": round(swap0)},
        "lowest_free_pct": lowest_free,
        "swap_growth_mb": round(highest_swap - swap0),
        "lazis_cpu_pct": stats(totals_cpu),
        "lazis_rss_mb": stats(totals_mem),
        "by_process": {r: {"cpu_pct": stats(v["cpu"]), "rss_mb": stats(v["rss"])} for r, v in sorted(per.items())},
    }


def report_log(directory: Path) -> dict[str, object]:
    values: dict[str, list[float]] = {}
    for f in sorted(directory.glob("desktop*.log")):
        for line in f.read_text(errors="ignore").splitlines():
            m = re.search(r"metrics\.(\w+) value=([\d.]+) detail=(\S+)", line)
            if m:
                key = m.group(1) if m.group(3) == "-" else f"{m.group(1)}_{m.group(3)}"
                values.setdefault(key, []).append(float(m.group(2)))
    out: dict[str, object] = {}
    for k, v in sorted(values.items()):
        s = stats(v)
        if k.startswith("fps") and v:
            s["worst"] = round(min(v), 1)  # for a frame rate the worst is the lowest
        out[k] = s
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=int, default=120)
    p.add_argument("--label", default="run")
    p.add_argument("--unload-on-stop", action="store_true")
    p.add_argument("--report-log", type=Path)
    a = p.parse_args()
    result = report_log(a.report_log.expanduser()) if a.report_log else sample(a.seconds, a.label, a.unload_on_stop)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
