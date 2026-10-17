"""Shared helpers for the Phase 2 evaluation runners (environment manifest, process memory).

Runners use the production adapter (lazis.providers.llm.ollama) so that benchmarks also
exercise the code LAZIS ships. Run them with the backend's environment:

    uv run --project core python evals/runners/perf.py --model qwen3.5:9b-q4_K_M
"""

from __future__ import annotations

import ctypes
import json
import platform
import re
import statistics
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "evals" / "reports" / "phase2"
OLLAMA = "http://127.0.0.1:11434"


def sh(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def proc_env(pid: int, prefix: bytes = b"OLLAMA_") -> list[str]:
    libc = ctypes.CDLL(None)
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(0)
    if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        return []
    return [p.decode() for p in buf.raw[4 : size.value].split(b"\0") if p.startswith(prefix)]


def footprint_mb(pid: int) -> float | None:
    """Physical footprint of a process (bytes precision; the default output rounds to 'GB')."""
    out = sh("/usr/bin/footprint", "-p", str(pid), "--format", "bytes")
    m = re.search(r"Footprint:\s+([\d.]+)\s*B", out)
    return round(float(m.group(1)) / 2**20, 1) if m else None


def runner_pids() -> list[int]:
    """Inference processes = children of the Ollama server (llama-server, MLX runner, ...)."""
    server = server_pid()
    if server is None:
        return []
    out = sh("/usr/bin/pgrep", "-P", str(server))
    return [int(p) for p in out.split()] if out else []


def runner_commands() -> list[str]:
    return [sh("/bin/ps", "-o", "comm=", "-p", str(pid)) for pid in runner_pids()]


def server_pid() -> int | None:
    out = sh("/usr/bin/pgrep", "-x", "ollama")
    return int(out.split()[0]) if out else None


def memory_state() -> dict[str, Any]:
    vm = sh("/usr/bin/vm_stat")
    page = 16384
    pages = {k.strip(): int(v.strip().rstrip(".")) for k, v in re.findall(r"^(.+?):\s+(\d+)\.?$", vm, re.M)}
    swap = sh("/usr/sbin/sysctl", "-n", "vm.swapusage")
    used = re.search(r"used = ([\d.]+)M", swap)
    pressure = sh("/usr/bin/memory_pressure", "-Q")
    free_pct = re.search(r"(\d+)%", pressure)
    gb = lambda key: round(pages.get(key, 0) * page / 2**30, 2)  # noqa: E731
    return {
        "free_gb": gb("Pages free"),
        "active_gb": gb("Pages active"),
        "wired_gb": gb("Pages wired down"),
        "compressed_gb": gb("Pages occupied by compressor"),
        "swap_used_mb": float(used.group(1)) if used else None,
        "swapouts": pages.get("Swapouts"),
        "memory_free_percent": int(free_pct.group(1)) if free_pct else None,
    }


def model_entry(model: str) -> dict[str, Any]:
    tags = httpx.get(f"{OLLAMA}/api/tags", timeout=5).json()["models"]
    entry = next(m for m in tags if m["name"] == model)
    show = httpx.post(f"{OLLAMA}/api/show", json={"model": model}, timeout=10).json()
    info = show.get("model_info", {})
    return {
        "name": model,
        "digest": entry["digest"],
        "size_bytes": entry["size"],
        "details": entry.get("details", {}),
        "capabilities": show.get("capabilities", []),
        "default_parameters": show.get("parameters", ""),
        "architecture": info.get("general.architecture"),
        "parameter_count": info.get("general.parameter_count"),
        "context_length_max": next(
            (v for k, v in info.items() if k.endswith(".context_length")), None
        ),
    }


def manifest(model: str) -> dict[str, Any]:
    pid = server_pid()
    return {
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": sh("/usr/sbin/sysctl", "-n", "hw.model"),
        "chip": sh("/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"),
        "memory_gb": int(sh("/usr/sbin/sysctl", "-n", "hw.memsize") or 0) // 2**30,
        "macos": platform.mac_ver()[0],
        "ollama_version": httpx.get(f"{OLLAMA}/api/version", timeout=5).json()["version"],
        "ollama_env": proc_env(pid) if pid else [],
        # Power source and charge only; the battery line also carries an IORegistry id, dropped.
        "power": [re.sub(r"\s*\(id=\d+\)", "", line) for line in sh("/usr/bin/pmset", "-g", "batt").splitlines()[:2]],
        "thermal": sh("/usr/bin/pmset", "-g", "therm").splitlines(),
        "memory": memory_state(),
        "model": model_entry(model),
    }


def summarize(values: list[float]) -> dict[str, float | int | None]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return {"n": 0, "median": None, "p95": None, "min": None, "max": None}
    p95 = vals[min(len(vals) - 1, round(0.95 * (len(vals) - 1)))]
    return {
        "n": len(vals),
        "median": round(statistics.median(vals), 2),
        "p95": round(p95, 2),
        "min": round(vals[0], 2),
        "max": round(vals[-1], 2),
    }


def slug(model: str) -> str:
    return model.replace(":", "_").replace("/", "_")


def write_report(model: str, name: str, data: dict[str, Any]) -> Path:
    out = REPORTS / slug(model)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return path
