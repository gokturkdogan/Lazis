"""Runs the missing runs of p10p_compaction_long.py apart from the editor, and stops them safely.

    uv run --project core python evals/runners/p10p_supervise.py --detach --label baseline --run 3

The runner is unchanged, so results stay comparable. A run starts only when every start condition holds
for 30 s, and those conditions are kept with it; ``--check`` shows them and starts nothing. This process has its own session and parent
(launchd), so closing the editor or the assistant does not end it. It starts each missing gap as one
runner process; a finished report is never run again.

Kept in <out>/<label>_r<run>_progress/: status.json (current state), monitor.jsonl (system samples),
runs.jsonl (one line per finished or stopped run), gap<g>.turns.jsonl (one line per turn, flushed by
the runner) and gap<g>.stderr.txt, plus the memory files described in p10p_memwatch.py. A stopped run
writes no report and counts as incomplete. A warning is recorded and does not stop a run, unless
this run asks for it with ``--stop-on-flags`` or ``--stop-swap-growth-mb`` (off by default).

To stop by hand: touch <progress>/STOP
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from p10p_memwatch import VERY_SLOW_SAMPLES, MemoryLog, other_programs, processes, program

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_OUT = REPO / "evals" / "reports" / "phase10" / "perf"
PORT = 11499
START_WAIT_S = 900
START_FOOTPRINT_MB = 10 * 1024  # the owner's limits, 2026-11-03
START_SWAP_MB = 10752  # 10.5 GB
START_STABLE_S = 30
RUN_LIMIT_S = 3 * 3600
BATTERY_TOLERANCE_S = 60  # a loose cable for a few seconds should not end an hour's run
SWAP_LIMIT_MB = 24 * 1024  # the machine's physical memory; earlier runs peaked at 19.3 GB
DISK_FREE_MIN_GB = 20
SLEEP_GAP_S = 15
STALL_GAP_S = 30
TERMINAL = ("done", "stopped", "failed")


def cmd(args: list[str], timeout: float = 30) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout


def sample(pgid: int | None, pressure_file: str | None) -> dict[str, Any]:
    row: dict[str, Any] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if pressure_file:
        row["pressure_level"] = int(Path(pressure_file).read_text().strip() or 1)
    else:
        row["pressure_level"] = int(cmd(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip() or 0)
    swap = cmd(["sysctl", "-n", "vm.swapusage"])
    for key, name in (("used", "swap_used_mb"), ("total", "swap_total_mb")):
        m = re.search(rf"{key} = ([\d.]+)M", swap)
        row[name] = round(float(m.group(1))) if m else None
    pages = {m[0]: int(m[1]) for m in re.findall(r"^(.+?):\s+(\d+)\.$", cmd(["vm_stat"]), re.M)}
    mb = 16384 / 1024 / 1024
    row["used_mb"] = round(
        (pages.get("Pages active", 0) + pages.get("Pages wired down", 0)
         + pages.get("Pages occupied by compressor", 0)) * mb
    )  # fmt: skip
    row["compressed_mb"] = round(pages.get("Pages occupied by compressor", 0) * mb)
    row["ac_power"] = "AC Power" in cmd(["pmset", "-g", "batt"])
    row["load_1m"] = round(os.getloadavg()[0], 2)
    row["disk_free_gb"] = shutil.disk_usage("/").free // 1024**3
    if pgid is not None:
        rss = 0
        for line in cmd(["ps", "-A", "-o", "pgid=,rss="]).splitlines():
            parts = line.split()
            if len(parts) == 2 and int(parts[0]) == pgid:
                rss = max(rss, int(parts[1]))
        row["largest_process_rss_mb"] = rss // 1024
    return row


def busiest() -> list[str]:
    """The three busiest programs, by name only: other apps' arguments stay out of the records."""
    rows = cmd(["ps", "-A", "-r", "-o", "pcpu=,comm="]).splitlines()[:3]
    return [f"{r.split(None, 1)[0]} {Path(r.split(None, 1)[1]).name}" for r in rows if len(r.split(None, 1)) == 2]


def stop_reason(row: dict[str, Any], battery_s: float, wall_gap: float, mono_gap: float, poll: float) -> str | None:
    """Why a run must end now, or None. One critical sample is enough: the owner's rule has no tolerance."""
    if row["pressure_level"] >= 4:
        return "memory_pressure_critical"
    if wall_gap - mono_gap > SLEEP_GAP_S:
        return "machine_slept"
    if mono_gap > poll + STALL_GAP_S:
        return "system_stalled"
    if battery_s > BATTERY_TOLERANCE_S:
        return "on_battery"
    if (row.get("swap_used_mb") or 0) >= SWAP_LIMIT_MB:
        return "swap_limit"
    if row["disk_free_gb"] < DISK_FREE_MIN_GB:
        return "disk_low"
    return None


def caution_stop(flags: dict[str, int], rules: str | None, swap_growth_mb: float, swap_limit_mb: int | None) -> str | None:
    """The stops a run opts into. Rules look like ``long_warning,slow_response:3``: flag, times seen."""
    for rule in (rules or "").split(","):
        name, _, times = rule.strip().partition(":")
        if name and flags.get(name, 0) >= int(times or 1):
            return f"flag_{name}"
    if swap_limit_mb is not None and swap_growth_mb >= swap_limit_mb:
        return "swap_growth_limit"
    return None


class Supervisor:
    def __init__(self, a: argparse.Namespace) -> None:
        self.a = a
        self.out = Path(a.out)
        self.dir = self.out / f"{a.label}_r{a.run}_progress"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stop_file = self.dir / "STOP"
        self.status: dict[str, Any] = {"state": "starting", "pid": os.getpid(), "label": a.label, "run": a.run}
        self.mem = MemoryLog(self.dir, a.pressure_file)
        self.last_conditions: dict[str, Any] | None = None
        self.swap_at_start: float | None = None

    def save(self, **changes: Any) -> None:
        self.status.update(changes, updated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        tmp = self.dir / "status.tmp"
        tmp.write_text(json.dumps(self.status, ensure_ascii=False, indent=1) + "\n")
        tmp.replace(self.dir / "status.json")

    def append(self, name: str, row: dict[str, Any]) -> None:
        with (self.dir / name).open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def report_path(self, gap: str) -> Path:
        return self.out / f"{self.a.label}_cache{self.a.cache_ram}_gap{gap}_r{self.a.run}.json"

    def hashes(self) -> dict[str, str]:
        files = self.out.glob(self.a.keep_glob or f"{self.a.label}_*.json")
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}

    def port_free(self) -> bool:
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", PORT)) != 0

    def conditions(self) -> dict[str, Any]:
        """Every start condition with its value; running this starts nothing."""
        row = sample(None, self.a.pressure_file)
        total, top = other_programs()
        lazis = bool(cmd(["pgrep", "-x", "LAZIS"]).strip()) or "LAZIS" in top
        clamshell = cmd(["ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"])
        running = {program(r["comm"], r["pgid"]) for r in processes()}
        wanted = [x.strip() for x in (self.a.expect_apps or "").split(",") if x.strip()]
        loaded = cmd(["ollama", "ps"]).strip().splitlines()[1:]  # with none loaded, the runner's unload does nothing
        checks = {
            "ac_power": {"value": row["ac_power"], "ok": row["ac_power"]},
            "lid_open": {"value": '"AppleClamshellState" = No' in clamshell,
                         "ok": '"AppleClamshellState" = No' in clamshell},
            "lazis_closed": {"value": not lazis, "ok": not lazis},
            "pressure_normal": {"value": row["pressure_level"], "ok": row["pressure_level"] == 1},
            "other_programs_footprint_mb": {"value": total, "limit": self.a.start_footprint_mb,
                                            "ok": total <= self.a.start_footprint_mb},
            "swap_used_mb": {"value": row["swap_used_mb"], "limit": self.a.start_swap_mb,
                             "ok": (row["swap_used_mb"] or 0) <= self.a.start_swap_mb},
            "disk_free_gb": {"value": row["disk_free_gb"], "limit": DISK_FREE_MIN_GB,
                             "ok": row["disk_free_gb"] >= DISK_FREE_MIN_GB},
            "test_port_free": {"value": self.port_free(), "ok": self.port_free()},
            "service_has_no_model_loaded": {"value": len(loaded) == 0, "ok": len(loaded) == 0},
        }  # fmt: skip
        return {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "ok": all(c["ok"] for c in checks.values()),
                "checks": checks, "largest_programs_mb": top, "other_programs_footprint_mb": total,
                "expected_apps": {x: x in running for x in wanted}}  # fmt: skip

    def wait_until_ready(self) -> str | None:
        t0 = time.monotonic()
        held_since: float | None = None
        failed: list[str] = []
        while True:
            if self.stop_file.exists():
                return "stopped_by_hand"
            found = self.conditions()
            self.last_conditions = found
            (self.dir / "start_conditions.json").write_text(json.dumps(found, ensure_ascii=False, indent=1) + "\n")
            now = time.monotonic()
            failed = [k for k, c in found["checks"].items() if not c["ok"]]
            held_since = (held_since or now) if not failed else None
            if held_since is not None and now - held_since >= self.a.start_stable:
                return None
            if now - t0 > self.a.start_wait:
                return f"not_ready_at_start: {', '.join(failed) or 'not stable'}"
            self.save(state="waiting", waiting_for=failed)
            self.mem.check_level()
            time.sleep(min(self.a.poll, 10))

    def run_gap(self, gap: str) -> str | None:
        turns_path = self.dir / f"gap{gap}.turns.jsonl"
        with turns_path.open("a") as out, (self.dir / f"gap{gap}.stderr.txt").open("a") as err:
            before = set(Path(tempfile.gettempdir()).glob("lazis-p6s-*"))
            started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            proc = subprocess.Popen(
                [sys.executable, "-u", self.a.runner, "--model", self.a.model, "--label", self.a.label,
                 "--cache-ram", str(self.a.cache_ram), "--gaps", gap, "--runs", str(self.a.run)],
                cwd=HERE, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True,
                env={**os.environ, "LAZIS_EVAL_OUT": str(self.out)},
            )  # fmt: skip
            self.mem.run_pgid = proc.pid
            self.mem.reset_run()
            why = self.watch(proc, gap, turns_path)
        if why is not None:
            self.end_runner(proc)
        elif proc.returncode != 0 or not self.report_path(gap).exists():
            why = f"runner_failed: exit {proc.returncode}"
        for leftover in set(Path(tempfile.gettempdir()).glob("lazis-p6s-*")) - before:
            shutil.rmtree(leftover, ignore_errors=True)
        self.record(gap, started, why, turns_path)
        return why

    def watch(self, proc: subprocess.Popen[bytes], gap: str, turns_path: Path) -> str | None:
        poll = self.a.poll
        wall, mono = time.time(), time.monotonic()
        t0 = mono
        battery_since: float | None = None
        n = 0
        while proc.poll() is None:
            end = time.monotonic() + poll
            late = 0.0
            while time.monotonic() < end and proc.poll() is None and self.mem.check_level() < 4:
                early = self.early_stop(turns_path)
                if early:
                    return early
                pause = min(1, poll)
                before = time.monotonic()
                time.sleep(pause)
                late = max(late, (time.monotonic() - before - pause) * 1000)
            if self.stop_file.exists():
                return "stopped_by_hand"
            try:
                row = sample(proc.pid, self.a.pressure_file)
                detail = self.mem.tick(late)
            except subprocess.TimeoutExpired:
                return "system_stalled"
            row["pressure_level"] = max(row["pressure_level"], detail["worst_level_since_last_sample"])
            if self.mem.very_slow_samples >= VERY_SLOW_SAMPLES:
                self.append("monitor.jsonl", {**row, "gap": gap, **detail})
                return "machine_very_slow"
            now_w, now_m = time.time(), time.monotonic()
            battery_since = (battery_since or now_m) if not row["ac_power"] else None
            battery_s = now_m - battery_since if battery_since else 0.0
            self.swap_at_start = row.get("swap_used_mb") if self.swap_at_start is None else self.swap_at_start
            why = stop_reason(row, battery_s, now_w - wall, now_m - mono, poll) or caution_stop(
                self.mem.flags, self.a.stop_on_flags, (row.get("swap_used_mb") or 0) - (self.swap_at_start or 0),
                self.a.stop_swap_growth_mb,
            )  # fmt: skip
            wall, mono = now_w, now_m
            n += 1
            if n % 12 == 1:
                row["busiest"] = busiest()
            row["gap"] = gap
            row.update(detail)
            self.append("monitor.jsonl", row)
            done, last = self.turns(turns_path)
            self.save(state="running", gap=gap, turns_done=done, last_first_token_s=last, pressure=row["pressure_level"],
                      swap_used_mb=row["swap_used_mb"], ac_power=row["ac_power"], **self.mem.summary())  # fmt: skip
            if why:
                return why
            if now_m - t0 > self.a.run_limit:
                return "run_time_limit"
        return None

    def early_stop(self, turns_path: Path) -> str | None:
        if self.stop_file.exists():
            return "stopped_by_hand"
        if self.a.stop_after_turns and self.turns(turns_path)[0] >= self.a.stop_after_turns:
            return "stop_after_turns"
        return None

    def turns(self, path: Path) -> tuple[int, float | None]:
        done, last = 0, None
        for line in path.read_text().splitlines():
            if line.startswith('{"i":'):
                done, last = done + 1, json.loads(line).get("first_s")
        return done, last

    def end_runner(self, proc: subprocess.Popen[bytes]) -> None:
        """SIGINT lets the runner's finally stop the engine, the private server and the temp profile."""
        steps = ((proc.send_signal, signal.SIGINT, 90), (self.group, signal.SIGTERM, 20), (self.group_kill, 0, 10))
        pgid = proc.pid
        self._pgid = pgid
        for send, sig, wait in steps:
            with contextlib.suppress(ProcessLookupError):
                send(sig)
            try:
                proc.wait(wait)
                break
            except subprocess.TimeoutExpired:
                continue
        with contextlib.suppress(ProcessLookupError):  # whatever it left behind, like its private server
            os.killpg(pgid, signal.SIGTERM)

    def group(self, sig: int) -> None:
        os.killpg(self._pgid, sig)

    def group_kill(self, _: int) -> None:
        os.killpg(self._pgid, signal.SIGKILL)

    def record(self, gap: str, started: str, why: str | None, turns_path: Path) -> None:
        row: dict[str, Any] = {"gap": gap, "started": started, "ended": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                               "complete": why is None, "reason": why, "turns_done": self.turns(turns_path)[0],
                               "condition": self.a.condition, "start_conditions": self.last_conditions,
                               "memory_watch": self.mem.summary()}  # fmt: skip
        if why is None:
            d = json.loads(self.report_path(gap).read_text())
            jobs = d.get("memory_jobs", {})
            row.update(
                report=self.report_path(gap).name, code=d.get("code"), latency=d.get("latency"),
                memory_system=d.get("memory_system"), settle=d.get("settle"), memory_jobs=jobs,
                memory_complete=not jobs.get("queued") and not jobs.get("running"),
                compaction_ms=[c.get("duration_ms") for c in d.get("compactions", [])],
            )  # fmt: skip
        self.append("runs.jsonl", row)

    def run(self) -> int:
        caffeinate = subprocess.Popen(["caffeinate", "-is", "-w", str(os.getpid())])
        kept = self.hashes()
        (self.dir / "kept_reports.sha256.json").write_text(json.dumps(kept, indent=1) + "\n")
        self.save(state="starting", gaps=self.a.gaps, kept_reports=len(kept), condition=self.a.condition,
                  limits={"footprint_mb": self.a.start_footprint_mb, "swap_mb": self.a.start_swap_mb})  # fmt: skip
        why = None
        for gap in self.a.gaps.split(","):
            if self.report_path(gap).exists():
                continue
            why = self.wait_until_ready()
            if why is None:
                self.save(state="running", gap=gap, turns_done=0, waiting_for=None, load_at_start=os.getloadavg()[0])
                why = self.run_gap(gap)
            if why is not None:
                break
        changed = [k for k, v in kept.items() if self.hashes().get(k) != v]
        caffeinate.terminate()
        if changed:
            self.save(state="failed", reason=f"kept reports changed: {changed}")
            return 1
        self.save(state="stopped" if why else "done", reason=why, port_free=self.port_free(), **self.mem.summary())
        return 0 if why is None else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:12b-it-qat")
    ap.add_argument("--label", required=True)
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--cache-ram", type=int, default=2048)
    ap.add_argument("--gaps", default="6,30,60")
    ap.add_argument("--detach", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--runner", default=str(HERE / "p10p_compaction_long.py"))
    ap.add_argument("--poll", type=float, default=5)
    ap.add_argument("--start-wait", type=float, default=START_WAIT_S)
    ap.add_argument("--run-limit", type=float, default=RUN_LIMIT_S)
    ap.add_argument("--stop-after-turns", type=int, help="short trials: stop the run after this many turns")
    ap.add_argument("--check", action="store_true", help="show the start conditions and start nothing")
    ap.add_argument("--condition", help="how this system differs from earlier runs; kept with every run")
    ap.add_argument("--keep-glob", help="reports to fingerprint and protect (default: this label's)")
    ap.add_argument("--expect-apps", help="comma-separated programs of the planned environment; recorded, not required")
    ap.add_argument("--start-footprint-mb", type=int, default=START_FOOTPRINT_MB)
    ap.add_argument("--start-swap-mb", type=int, default=START_SWAP_MB)
    ap.add_argument("--start-stable", type=float, default=START_STABLE_S)
    ap.add_argument("--stop-on-flags", help="also stop on these flags, e.g. long_warning,slow_response:3")
    ap.add_argument("--stop-swap-growth-mb", type=int, help="also stop when swap has grown this much in the run")
    ap.add_argument("--pressure-file", help="tests only: read the pressure level from this file")
    a = ap.parse_args()
    # This process runs from the runners folder; a relative path here would silently mean another place.
    a.out, a.runner = str(Path(a.out).resolve()), str(Path(a.runner).resolve())
    a.pressure_file = str(Path(a.pressure_file).resolve()) if a.pressure_file else None
    if a.detach:
        progress = Path(a.out) / f"{a.label}_r{a.run}_progress"
        progress.mkdir(parents=True, exist_ok=True)
        argv = [x for x in sys.argv[1:] if x != "--detach"] + ["--out", a.out, "--runner", a.runner]
        argv += ["--pressure-file", a.pressure_file] if a.pressure_file else []
        with (progress / "supervisor.txt").open("a") as log:
            p = subprocess.Popen([sys.executable, "-u", __file__, *argv], stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=log, start_new_session=True, cwd=HERE)  # fmt: skip
        print(json.dumps({"pid": p.pid, "progress": str(progress), "stop_file": str(progress / "STOP")}))
        return 0
    if a.check:
        found = Supervisor(a).conditions()
        print(json.dumps(found, ensure_ascii=False, indent=1))
        return 0 if found["ok"] else 3
    return Supervisor(a).run()


if __name__ == "__main__":
    raise SystemExit(main())
