"""SPK-04 / SPK-05: SQLCipher + sqlite-vec + FTS5 compatibility and performance.

Synthetic data only, in a temporary directory that is deleted afterwards. Uses the same
driver module and keying code as the application.

    uv sync --group spike
    uv run python spikes/spk05_storage.py               # 50k x 768, about 2-3 minutes
    uv run python spikes/spk05_storage.py --rows 5000   # quick run
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import resource
import secrets
import sqlite3 as stdlib_sqlite3
import statistics
import tempfile
import time
from array import array
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import sqlite_vec

from lazis.security.secrets import SecretBytes
from lazis.storage.database import apply_key, file_is_plaintext_sqlite
from lazis.storage.driver import Connection, cipher_version, connect

K = 10
CACHE_DEFAULT = -2000  # SQLite default: about 2 MB
CACHE_LARGE = -262144  # 256 MB


def load_vec(conn: Any) -> str:
    conn.enable_load_extension(True)
    try:
        conn.load_extension(sqlite_vec.loadable_path())
    finally:
        # Never leave SQL-level load_extension() reachable.
        conn.enable_load_extension(False)
    return str(conn.execute("SELECT vec_version()").fetchone()[0])


def spk04() -> dict[str, Any]:
    out: dict[str, Any] = {}
    std = stdlib_sqlite3.connect(":memory:")
    out["stdlib_sqlite_version"] = stdlib_sqlite3.sqlite_version
    out["stdlib_has_enable_load_extension"] = hasattr(std, "enable_load_extension")
    try:
        out["stdlib_vec_version"] = load_vec(std)
    except Exception as exc:
        out["stdlib_vec_error"] = type(exc).__name__
    std.close()

    conn = connect(":memory:")
    out["cipher_version"] = cipher_version(conn)
    out["sqlite_version"] = conn.execute("SELECT sqlite_version()").fetchone()[0]
    options = {r[0] for r in conn.execute("PRAGMA compile_options")}
    out["compile_fts5"] = "ENABLE_FTS5" in options
    out["compile_omit_load_extension"] = "OMIT_LOAD_EXTENSION" in options
    out["sqlcipher_vec_version"] = load_vec(conn)
    try:
        conn.execute("SELECT load_extension('x')")
        out["sql_load_extension_after_disable"] = "ALLOWED (bad)"
    except Exception:
        out["sql_load_extension_after_disable"] = "refused"
    conn.execute("CREATE VIRTUAL TABLE f USING fts5(body)")
    conn.execute("INSERT INTO f VALUES ('merhaba dünya')")
    out["fts5_works"] = (
        conn.execute("SELECT count(*) FROM f WHERE f MATCH 'dünya'").fetchone()[0] == 1
    )
    conn.close()
    return out


def open_db(path: Path, key: SecretBytes | None, cache: int) -> Connection:
    conn = connect(path)
    if key is not None:
        apply_key(conn, key)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA cache_size={cache}")
    conn.execute("PRAGMA temp_store=MEMORY")
    load_vec(conn)
    return conn


def make_vectors(rows: int, dim: int, rng: random.Random) -> list[bytes]:
    return [array("f", [rng.random() - 0.5 for _ in range(dim)]).tobytes() for _ in range(rows)]


def make_int8(rows: int, dim: int, rng: random.Random) -> list[bytes]:
    return [bytes(rng.getrandbits(8) for _ in range(dim)) for _ in range(rows)]


def make_vocab(n: int, rng: random.Random) -> list[str]:
    syllables = [
        "ka",
        "le",
        "mi",
        "su",
        "ra",
        "de",
        "yo",
        "lu",
        "şe",
        "çi",
        "ğa",
        "ön",
        "ül",
        "ız",
        "ba",
        "te",
    ]
    vocab: set[str] = set()
    while len(vocab) < n:
        vocab.add("".join(rng.choice(syllables) for _ in range(rng.randint(2, 4))))
    return sorted(vocab)


def timed(fn: Callable[[], object], repeat: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return {
        "p50_ms": round(statistics.median(samples), 2),
        "p95_ms": round(samples[max(0, int(len(samples) * 0.95) - 1)], 2),
        "max_ms": round(samples[-1], 2),
    }


def bench_vectors(
    tmp: Path,
    label: str,
    key: SecretBytes | None,
    column: str,
    data: Sequence[bytes],
    queries: Sequence[bytes],
    wrap: str,
) -> dict[str, Any]:
    path = tmp / f"{label}.db"
    conn = open_db(path, key, CACHE_LARGE)
    conn.execute(f"CREATE VIRTUAL TABLE items USING vec0(embedding {column})")
    t0 = time.perf_counter()
    conn.execute("BEGIN")
    conn.executemany(
        f"INSERT INTO items(rowid, embedding) VALUES (?, {wrap}(?))",
        ((i + 1, v) for i, v in enumerate(data)),
    )
    conn.execute("COMMIT")
    insert_s = time.perf_counter() - t0
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    result: dict[str, Any] = {
        "insert_s": round(insert_s, 2),
        "size_mb": round(path.stat().st_size / 1e6, 1),
        "plaintext_header": file_is_plaintext_sqlite(path),
    }
    sql = f"SELECT rowid, distance FROM items WHERE embedding MATCH {wrap}(?) AND k = {K}"
    qi = iter(queries * 4)
    for cache_label, cache in (("cache_2mb", CACHE_DEFAULT), ("cache_256mb", CACHE_LARGE)):
        conn = open_db(path, key, cache)
        t0 = time.perf_counter()
        first = conn.execute(sql, (next(qi),)).fetchall()
        cold = (time.perf_counter() - t0) * 1000
        assert len(first) == K
        result[cache_label] = {
            "first_query_ms": round(cold, 1),
            **timed(lambda c=conn: c.execute(sql, (next(qi),)).fetchall(), len(queries)),
        }
        conn.close()
    return result


def bench_fts(
    tmp: Path,
    label: str,
    key: SecretBytes | None,
    docs: Sequence[str],
    terms: Sequence[str],
) -> dict[str, Any]:
    path = tmp / f"{label}.db"
    conn = open_db(path, key, CACHE_LARGE)
    conn.execute(
        "CREATE VIRTUAL TABLE notes USING fts5(body, tokenize='unicode61 remove_diacritics 2')"
    )
    t0 = time.perf_counter()
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO notes(rowid, body) VALUES (?, ?)", enumerate(docs, 1))
    conn.execute("COMMIT")
    insert_s = time.perf_counter() - t0
    conn.execute("INSERT INTO notes(notes) VALUES ('optimize')")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    conn = open_db(path, key, CACHE_DEFAULT)
    sql = "SELECT rowid, bm25(notes) FROM notes WHERE notes MATCH ? ORDER BY bm25(notes) LIMIT 20"
    ti = iter(list(terms) * 4)
    single = timed(lambda: conn.execute(sql, (next(ti),)).fetchall(), len(terms))
    pair = timed(
        lambda: conn.execute(sql, (f"{next(ti)} OR {next(ti)}",)).fetchall(), len(terms) // 2
    )
    conn.close()
    return {
        "insert_s": round(insert_s, 2),
        "size_mb": round(path.stat().st_size / 1e6, 1),
        "plaintext_header": file_is_plaintext_sqlite(path),
        "single_term": single,
        "two_terms_or": pair,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--dim", type=int, default=768)
    parser.add_argument("--queries", type=int, default=40)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    rng = random.Random(20261017)
    report: dict[str, Any] = {
        "machine": f"{platform.machine()} macOS {platform.mac_ver()[0]}",
        "python": platform.python_version(),
        "rows": args.rows,
        "dim": args.dim,
        "k": K,
        "spk04": spk04(),
    }
    key = SecretBytes(secrets.token_bytes(32))

    with tempfile.TemporaryDirectory(prefix="lazis-spk05-") as tmpdir:
        tmp = Path(tmpdir)
        print(f"generating {args.rows} x {args.dim} synthetic vectors ...", flush=True)
        floats = make_vectors(args.rows, args.dim, rng)
        fq = make_vectors(args.queries, args.dim, rng)
        vec: dict[str, Any] = {}
        for label, k in (("float32_plain", None), ("float32_encrypted", key)):
            print(f"vectors: {label}", flush=True)
            vec[label] = bench_vectors(tmp, label, k, f"float[{args.dim}]", floats, fq, "")
        del floats
        ints = make_int8(args.rows, args.dim, rng)
        iq = make_int8(args.queries, args.dim, rng)
        print("vectors: int8_encrypted", flush=True)
        vec["int8_encrypted"] = bench_vectors(
            tmp, "int8_encrypted", key, f"int8[{args.dim}]", ints, iq, "vec_int8"
        )
        del ints
        report["vectors"] = vec

        vocab = make_vocab(3000, rng)
        docs = [" ".join(rng.choices(vocab, k=rng.randint(20, 80))) for _ in range(args.rows)]
        terms = rng.sample(vocab, args.queries)
        fts: dict[str, Any] = {}
        for label, k in (("plain", None), ("encrypted", key)):
            print(f"fts5: {label}", flush=True)
            fts[label] = bench_fts(tmp, f"fts_{label}", k, docs, terms)
        report["fts5"] = fts

    report["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
