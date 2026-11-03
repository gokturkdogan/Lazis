"""Memory by program, with timestamps, for the compaction latency work. Reads only; closes nothing.

    uv run --project core python evals/runners/p10p_memwatch.py --seconds 60 --out DIR

Used by p10p_supervise.py during runs, or alone as above. Files in DIR:

- pressure_events.jsonl: every change of the macOS pressure level, warning included, with physical
  memory, memory per program and what changed since the last sample.
- ALERTS.txt: the same changes, one readable line each.
- process_memory.jsonl: footprint and compressed memory per program, every 30 s and on each change.

The level is read every second. ``ps`` (RSS) is cheap enough for every sample; ``top`` (footprint and
compressed memory) takes about a second, so it runs only every 30 s. RSS counts mapped model files and
shared pages; footprint counts compressed and swapped pages too. Neither alone says what closing a
program would free, so both are kept. Program names only: never arguments or window titles.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

FULL_SNAPSHOT_S = 30
CHANGE_MIN_MB = 100
LEVELS = {1: "normal", 2: "warning", 4: "critical"}
ALIASES = {"Visual Studio Code": "VS Code", "Microsoft Teams": "Teams", "Microsoft Outlook": "Outlook"}
UNITS = {"B": 1 / 1024 / 1024, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}
SIZE = re.compile(r"^([\d.]+)([BKMGT])[+-]?$")


def cmd(args: list[str], timeout: float = 30) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout


def program(comm: str, pgid: int, run_pgid: int | None = None) -> str:
    """The program a process belongs to, from its executable path."""
    base = Path(comm).name
    is_ollama = "ollama" in comm.lower() or base == "llama-server"
    if run_pgid is not None and pgid == run_pgid:
        return "Ollama (test runtime)" if is_ollama else "Eval runner"
    if is_ollama:
        return "Ollama (service)"
    if "anthropic.claude-code" in comm:
        return "Claude Code"
    if base.lower().startswith("lazis"):
        return "LAZIS"
    if "codex" in comm.lower():  # it may live inside another app's bundle, and is asked about by name
        return "Codex"
    app = re.search(r"([^/]+)\.app/", comm)
    if app:
        return ALIASES.get(app.group(1), app.group(1))
    # A process may rename itself, for example "Cursor Helper (Plugin): <window>": keep the program only.
    name = re.sub(r"( Helper\b.*|:.*)$", "", base)
    return ALIASES.get(name, name)


def processes() -> list[dict[str, Any]]:
    rows = []
    for line in cmd(["ps", "-A", "-o", "pid=,pgid=,rss=,comm="]).splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            rows.append({"pid": int(parts[0]), "pgid": int(parts[1]), "rss_mb": int(parts[2]) / 1024, "comm": parts[3]})
    return rows


def rss_by_program(rows: list[dict[str, Any]], run_pgid: int | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in rows:
        name = program(r["comm"], r["pgid"], run_pgid)
        out[name] = out.get(name, 0) + r["rss_mb"]
    return out


def size_mb(text: str) -> float:
    m = SIZE.match(text)
    return float(m.group(1)) * UNITS[m.group(2)] if m else 0.0


def footprints() -> dict[int, tuple[float, float]]:
    """pid → (footprint, compressed) in MB, from one ``top`` pass."""
    out: dict[int, tuple[float, float]] = {}
    for line in cmd(["top", "-l", "1", "-stats", "pid,mem,cmprs"]).splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0].isdigit():
            out[int(parts[0])] = (size_mb(parts[1]), size_mb(parts[2]))
    return out


def physical() -> dict[str, Any]:
    """Machine-wide memory, in MB."""
    text = cmd(["vm_stat"])
    size = re.search(r"page size of (\d+) bytes", text)
    mb = (int(size.group(1)) if size else 16384) / 1024 / 1024
    pages = {m[0]: int(m[1]) for m in re.findall(r"^\"?(.+?)\"?:\s+(\d+)\.$", text, re.M)}
    row = {
        name: round(pages.get(key, 0) * mb)
        for name, key in (
            ("free", "Pages free"), ("active", "Pages active"), ("inactive", "Pages inactive"),
            ("speculative", "Pages speculative"), ("wired", "Pages wired down"), ("purgeable", "Pages purgeable"),
            ("file_backed", "File-backed pages"), ("anonymous", "Anonymous pages"),
            ("compressor", "Pages occupied by compressor"), ("compressed_logical", "Pages stored in compressor"),
        )
    }  # fmt: skip
    row["total"] = int(cmd(["sysctl", "-n", "hw.memsize"]).strip() or 0) // 1024**2
    swap = cmd(["sysctl", "-n", "vm.swapusage"])
    for key, name in (("used", "swap_used"), ("total", "swap_total")):
        m = re.search(rf"{key} = ([\d.]+)M", swap)
        row[name] = round(float(m.group(1))) if m else 0
    row["swapouts"] = pages.get("Swapouts", 0)
    row["swapins"] = pages.get("Swapins", 0)
    return row


def rounded_top(values: dict[str, float], n: int = 15) -> dict[str, int]:
    return {k: round(v) for k, v in sorted(values.items(), key=lambda x: -x[1])[:n]}


class MemoryLog:
    def __init__(self, folder: Path, pressure_file: str | None = None) -> None:
        self.dir = folder
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pressure_file = pressure_file
        self.run_pgid: int | None = None
        self.level: int | None = None
        self.level_since = time.monotonic()
        self.worst_since_tick = 0
        self.seconds_at = {name: 0.0 for name in LEVELS.values()}
        self.events = 0
        self.last_rss: dict[str, float] = {}
        self.last_full = 0.0

    def stamp(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def append(self, name: str, row: dict[str, Any]) -> None:
        with (self.dir / name).open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def read_level(self) -> int:
        if self.pressure_file:
            return int(Path(self.pressure_file).read_text().strip() or 1)
        return int(cmd(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip() or 0)

    def rss(self) -> tuple[dict[str, float], dict[str, int]]:
        now = rss_by_program(processes(), self.run_pgid)
        changes = {
            k: round(now.get(k, 0) - self.last_rss.get(k, 0))
            for k in now.keys() | self.last_rss.keys()
            if abs(now.get(k, 0) - self.last_rss.get(k, 0)) >= CHANGE_MIN_MB
        } if self.last_rss else {}  # fmt: skip
        self.last_rss = now
        return now, changes

    def full(self, trigger: str) -> dict[str, Any]:
        """Footprint and compressed memory per program, written to process_memory.jsonl."""
        self.last_full = time.monotonic()
        tops = footprints()
        out: dict[str, dict[str, float]] = {}
        for r in processes():
            name = program(r["comm"], r["pgid"], self.run_pgid)
            foot, comp = tops.get(r["pid"], (0.0, 0.0))
            row = out.setdefault(name, {"rss_mb": 0.0, "footprint_mb": 0.0, "compressed_mb": 0.0, "processes": 0})
            row["rss_mb"] += r["rss_mb"]
            row["footprint_mb"] += foot
            row["compressed_mb"] += comp
            row["processes"] += 1
        ranked = sorted(out.items(), key=lambda x: -x[1]["footprint_mb"])
        table = {k: {a: round(b) for a, b in v.items()} for k, v in ranked[:25]}
        self.append("process_memory.jsonl", {"at": self.stamp(), "trigger": trigger, "programs": table})
        return table

    def check_level(self) -> int:
        """Read the level; on any change, record it with everything needed to explain it."""
        level = self.read_level()
        self.worst_since_tick = max(self.worst_since_tick, level)
        if level == self.level:
            return level
        now = time.monotonic()
        old = self.level
        if old is not None:
            self.seconds_at[LEVELS.get(old, str(old))] = self.seconds_at.get(LEVELS.get(old, str(old)), 0) + now - self.level_since
        self.level, self.level_since = level, now
        if old is None:
            return level
        self.events += 1
        rss, changes = self.rss()
        row: dict[str, Any] = {
            "at": self.stamp(), "from": LEVELS.get(old, old), "to": LEVELS.get(level, level),
            "physical": physical(), "rss_by_program_mb": rounded_top(rss), "rss_changes_since_last_sample_mb": changes,
        }  # fmt: skip
        with contextlib.suppress(subprocess.TimeoutExpired):  # the record above matters more than this table
            row["footprint_by_program_mb"] = self.full(f"{LEVELS.get(old, old)}->{LEVELS.get(level, level)}")
        self.append("pressure_events.jsonl", row)
        with (self.dir / "ALERTS.txt").open("a") as f:
            f.write(f"{row['at']} {row['from']} -> {row['to']}: used swap {row['physical']['swap_used']} MB, "
                    f"compressor {row['physical']['compressor']} MB, free {row['physical']['free']} MB\n")  # fmt: skip
        return level

    def tick(self) -> dict[str, Any]:
        """One sample: machine, RSS per program, changes since the last one. Full table when due."""
        rss, changes = self.rss()
        worst, self.worst_since_tick = self.worst_since_tick, 0
        if time.monotonic() - self.last_full >= FULL_SNAPSHOT_S:
            self.full("periodic")
        return {"worst_level_since_last_sample": worst, "physical": physical(), "rss_by_program_mb": rounded_top(rss),
                "rss_changes_mb": changes}  # fmt: skip

    def summary(self) -> dict[str, Any]:
        seconds = dict(self.seconds_at)
        if self.level is not None:
            name = LEVELS.get(self.level, str(self.level))
            seconds[name] = seconds.get(name, 0) + time.monotonic() - self.level_since
        return {"pressure_changes": self.events, "seconds_at_level": {k: round(v) for k, v in seconds.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--poll", type=float, default=5)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    log = MemoryLog(Path(a.out))
    log.check_level()
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.seconds:
        log.append("monitor.jsonl", {"at": log.stamp(), "level": log.check_level(), **log.tick()})
        end = time.monotonic() + a.poll
        while time.monotonic() < end:
            time.sleep(1)
            log.check_level()
    log.full("final")
    print(json.dumps(log.summary()))


if __name__ == "__main__":
    main()
