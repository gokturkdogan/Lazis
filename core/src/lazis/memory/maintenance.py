"""Long-term upkeep of the memory store (runs at most once a day, in the background).

* The full-text index is checked against the rows (a contentless index cannot be compared
  term by term, so the document counts are compared) and rebuilt if they disagree; then it is
  optimized (segments merged, deleted terms gone).
* Duplicates that slipped in (two active records with the same subject, predicate and value)
  are folded into the older one; evidence is kept.
* Closed inbox items keep no text (also for items closed before this rule existed).
"""

from __future__ import annotations

from dataclasses import dataclass

from lazis.memory import repository as repo
from lazis.storage.driver import Connection
from lazis.storage.unit_of_work import UnitOfWork

LAST_RUN_KEY = "memory_maintenance_at"
INTERVAL_S = 24 * 3600


@dataclass(frozen=True)
class MaintenanceResult:
    reindexed: bool
    duplicates_folded: int
    inbox_cleared: int


def due(conn: Connection, now_epoch: float) -> bool:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (LAST_RUN_KEY,)).fetchone()
    return row is None or now_epoch - float(row[0]) >= INTERVAL_S


def run(conn: Connection, now_epoch: float) -> MaintenanceResult:
    rows = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
    indexed = int(conn.execute("SELECT COUNT(*) FROM memory_fts_docsize").fetchone()[0])
    reindexed = rows != indexed
    folded = 0
    with UnitOfWork(conn, kind="maintenance", actor="system", summary="hafıza bakımı") as uow:
        if reindexed:
            conn.execute("DELETE FROM memory_fts")
            for (mid,) in conn.execute("SELECT id FROM memories").fetchall():
                repo.reindex_memory(conn, str(mid))
        dupes = conn.execute(
            "SELECT COALESCE(subject_id, ''), predicate, value_key, GROUP_CONCAT(id)"
            " FROM (SELECT * FROM memories WHERE status = 'active' ORDER BY created_at)"
            " GROUP BY COALESCE(subject_id, ''), predicate, value_key HAVING COUNT(*) > 1"
        ).fetchall()
        for _sid, _pred, _key, ids in dupes:
            keep, *others = str(ids).split(",")
            for other in others:
                m = repo.get_memory(conn, other)
                if m is None:
                    continue
                before = uow.snapshot("memories", other)
                repo.move_evidence(conn, other, keep)
                repo.delete_memory(conn, m)
                uow.record("memories", other, "delete", before)
                folded += 1
        cleared = conn.execute(
            "UPDATE memory_inbox SET summary = '', payload_json = '{}'"
            " WHERE status != 'open' AND (summary != '' OR payload_json != '{}')"
        ).rowcount
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (LAST_RUN_KEY, str(now_epoch)),
        )
    repo.optimize_index(conn)
    return MaintenanceResult(reindexed, folded, cleared)
