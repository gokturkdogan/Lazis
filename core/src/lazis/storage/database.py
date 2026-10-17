"""Encrypted database lifecycle.

* SQLCipher only; refuses plaintext files and never creates an unencrypted database.
* Raw 256-bit key (``x'…'``): no passphrase KDF, the key is already random.
* Encryption is *verified*, not assumed: driver check, file-header check after first write.
* One dedicated thread owns the connection; async callers use :meth:`Database.run`.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from lazis.errors import (
    DatabaseCorruptError,
    DatabaseKeyError,
    EncryptionUnavailableError,
    PlaintextDatabaseError,
    StorageError,
)
from lazis.fsutil import ensure_private_dir, ensure_private_file
from lazis.security.secrets import SecretBytes
from lazis.storage import driver
from lazis.storage.driver import Connection

T = TypeVar("T")

PLAINTEXT_HEADER = b"SQLite format 3\x00"
SIDE_FILES = ("-wal", "-shm", "-journal")


def file_is_plaintext_sqlite(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(PLAINTEXT_HEADER)) == PLAINTEXT_HEADER


def apply_key(conn: Connection, key: SecretBytes) -> None:
    # The hex alphabet cannot break out of the literal; PRAGMA does not accept bound params.
    conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")


@dataclass(frozen=True)
class DatabaseStatus:
    path: str
    size_bytes: int
    encrypted: bool
    encryption_verified: bool
    cipher_version: str
    cipher_provider: str
    sqlite_version: str
    journal_mode: str
    quick_check: str


class Database:
    def __init__(self, path: Path, key: SecretBytes) -> None:
        self.path = path
        self._key = key
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lazis-db")
        self._conn: Connection | None = None
        self.cipher_version = ""
        self.sqlite_version = ""

    # ----- lifecycle -------------------------------------------------------------------
    def open(self) -> None:
        self._executor.submit(self._open_sync).result()

    def _open_sync(self) -> None:
        ensure_private_dir(self.path.parent)
        existed = self.path.exists() and self.path.stat().st_size > 0
        if existed and file_is_plaintext_sqlite(self.path):
            raise PlaintextDatabaseError("refusing to open a plaintext SQLite file")
        conn = driver.connect(self.path)
        try:
            version = driver.cipher_version(conn)
            if not version:
                raise EncryptionUnavailableError("SQLCipher is not active on this connection")
            apply_key(conn, self._key)
            try:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            except driver.DatabaseError:
                raise DatabaseKeyError("key does not open this database") from None
            for pragma in (
                "PRAGMA journal_mode = WAL",
                "PRAGMA synchronous = NORMAL",
                "PRAGMA foreign_keys = ON",
                "PRAGMA busy_timeout = 5000",
                "PRAGMA temp_store = MEMORY",
                "PRAGMA secure_delete = ON",
            ):
                conn.execute(pragma)
            self.cipher_version = version
            self.sqlite_version = str(conn.execute("SELECT sqlite_version()").fetchone()[0])
        except BaseException:
            conn.close()
            raise
        self._conn = conn
        self.fix_permissions()

    def close(self) -> None:
        if self._conn is None:
            self._executor.shutdown(wait=True)
            return

        def _close(conn: Connection) -> None:
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()

        try:
            self._executor.submit(_close, self._conn).result()
        finally:
            self._conn = None
            self._executor.shutdown(wait=True)

    # ----- execution -------------------------------------------------------------------
    def _require_conn(self) -> Connection:
        if self._conn is None:
            raise StorageError("database is not open")
        return self._conn

    def run_sync(self, fn: Callable[[Connection], T]) -> T:
        conn = self._require_conn()
        return self._executor.submit(fn, conn).result()

    async def run(self, fn: Callable[[Connection], T]) -> T:
        conn = self._require_conn()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, conn)

    # ----- verification ----------------------------------------------------------------
    def fix_permissions(self) -> None:
        ensure_private_file(self.path)
        for suffix in SIDE_FILES:
            ensure_private_file(Path(f"{self.path}{suffix}"))

    def verify_encrypted_on_disk(self) -> bool:
        """True once the file exists and does *not* start with the plaintext SQLite header."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return False
        return not file_is_plaintext_sqlite(self.path)

    def assert_encrypted_on_disk(self) -> None:
        if (
            self.path.exists()
            and self.path.stat().st_size > 0
            and file_is_plaintext_sqlite(self.path)
        ):
            raise EncryptionUnavailableError("database file has a plaintext header")

    def quick_check(self) -> str:
        def _check(conn: Connection) -> str:
            rows = conn.execute("PRAGMA quick_check").fetchall()
            return "ok" if rows == [("ok",)] else "failed"

        return self.run_sync(_check)

    def cipher_integrity_check(self) -> list[str]:
        def _check(conn: Connection) -> list[str]:
            return [str(r[0]) for r in conn.execute("PRAGMA cipher_integrity_check").fetchall()]

        return self.run_sync(_check)

    def require_healthy(self) -> None:
        if self.quick_check() != "ok" or self.cipher_integrity_check():
            raise DatabaseCorruptError("integrity check failed")

    def _status_fn(self, conn: Connection) -> DatabaseStatus:
        rows = conn.execute("PRAGMA quick_check").fetchall()
        provider_row = conn.execute("PRAGMA cipher_provider").fetchone()
        return DatabaseStatus(
            path=str(self.path),
            size_bytes=os.path.getsize(self.path) if self.path.exists() else 0,
            encrypted=True,
            encryption_verified=self.verify_encrypted_on_disk(),
            cipher_version=self.cipher_version,
            cipher_provider=str(provider_row[0]) if provider_row else "",
            sqlite_version=self.sqlite_version,
            journal_mode=str(conn.execute("PRAGMA journal_mode").fetchone()[0]),
            quick_check="ok" if rows == [("ok",)] else "failed",
        )

    def status(self) -> DatabaseStatus:
        return self.run_sync(self._status_fn)

    async def astatus(self) -> DatabaseStatus:
        return await self.run(self._status_fn)

    @property
    def key(self) -> SecretBytes:
        return self._key
