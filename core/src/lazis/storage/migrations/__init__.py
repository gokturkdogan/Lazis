"""Forward-only SQL migrations, one directory per database track (``lazis/`` for lazis.db)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources

from lazis.errors import MigrationError
from lazis.ids import utc_now_iso
from lazis.storage.driver import Connection, DatabaseError

FOREIGN_KEYS_OFF = "-- lazis:foreign-keys=off"
_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

_RUNNER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL
) STRICT;
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    @property
    def foreign_keys_off(self) -> bool:
        """A migration that rebuilds a referenced table declares ``-- lazis:foreign-keys=off``
        on its first line: SQLite's documented table-rebuild procedure needs foreign keys off
        (``DROP TABLE`` with them on would cascade-delete the referencing rows). The runner
        then checks ``PRAGMA foreign_key_check`` before committing."""
        return self.sql.lstrip().startswith(FOREIGN_KEYS_OFF)


@dataclass(frozen=True)
class MigrationResult:
    applied: tuple[int, ...]
    current_version: int


def load_migrations(track: str = "lazis") -> list[Migration]:
    folder = resources.files(__package__) / track
    found: list[Migration] = []
    for entry in folder.iterdir():
        match = _FILENAME.match(entry.name)
        if match:
            found.append(Migration(int(match.group(1)), match.group(2), entry.read_text("utf-8")))
    found.sort(key=lambda m: m.version)
    expected = list(range(1, len(found) + 1))
    if [m.version for m in found] != expected:
        raise MigrationError(f"migration versions for track '{track}' are not contiguous from 1")
    return found


def applied_migrations(conn: Connection) -> dict[int, tuple[str, str]]:
    conn.executescript(_RUNNER_DDL)
    rows = conn.execute("SELECT version, name, checksum FROM schema_migrations").fetchall()
    return {int(v): (str(n), str(c)) for v, n, c in rows}


def current_version(conn: Connection) -> int:
    return max(applied_migrations(conn), default=0)


def migrate(
    conn: Connection,
    migrations: Sequence[Migration],
    *,
    before_apply: Callable[[Connection, int, Sequence[Migration]], None] | None = None,
) -> MigrationResult:
    """Verify applied migrations, then apply pending ones, each atomically.

    ``before_apply(conn, current_version, pending)`` runs on the same connection (and thread)
    only when an existing schema is about to change — used for the pre-migration backup.
    """
    applied = applied_migrations(conn)
    known = {m.version: m for m in migrations}
    for version, (name, checksum) in sorted(applied.items()):
        migration = known.get(version)
        if migration is None:
            raise MigrationError(f"database schema v{version} is newer than this application")
        if migration.checksum != checksum or migration.name != name:
            raise MigrationError(f"applied migration v{version} was modified (checksum mismatch)")

    pending = [m for m in migrations if m.version not in applied]
    current = max(applied, default=0)
    if pending and applied and before_apply is not None:
        before_apply(conn, current, pending)

    done: list[int] = []
    for migration in pending:
        # Values come from validated file names and computed checksums, never from input.
        record = (
            "INSERT INTO schema_migrations (version, name, checksum, applied_at) "  # noqa: S608
            f"VALUES ({migration.version}, '{migration.name}', '{migration.checksum}', "
            f"'{utc_now_iso()}');\n"
        )
        try:
            if migration.foreign_keys_off:
                _apply_with_foreign_keys_off(conn, migration, record)
            else:
                conn.executescript(f"BEGIN IMMEDIATE;\n{migration.sql}\n{record}COMMIT;")
        except DatabaseError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(
                f"migration v{migration.version} failed ({exc.__class__.__name__})"
            ) from None
        done.append(migration.version)
        current = migration.version
    return MigrationResult(applied=tuple(done), current_version=current)


def _apply_with_foreign_keys_off(conn: Connection, migration: Migration, record: str) -> None:
    """SQLite's table-rebuild procedure: foreign keys off (outside any transaction), the
    migration in one transaction, ``foreign_key_check`` must be empty, then commit; foreign
    keys are switched back on whatever happens."""
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(f"BEGIN IMMEDIATE;\n{migration.sql}\n")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            conn.execute("ROLLBACK")
            raise MigrationError(
                f"migration v{migration.version} broke {len(violations)} foreign key(s)"
            )
        # Not executescript: it would COMMIT the open transaction before running.
        conn.execute(record.rstrip().rstrip(";"))
        conn.execute("COMMIT")
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.execute("PRAGMA foreign_keys = ON")
