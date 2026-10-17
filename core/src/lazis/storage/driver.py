"""The only module that imports the SQLCipher driver.

There is deliberately **no** fallback to the standard-library ``sqlite3``: if SQLCipher is
missing or inactive, :func:`verify_driver` raises and the application refuses to start.
"""

from __future__ import annotations

from pathlib import Path

import sqlcipher3
from sqlcipher3 import dbapi2

from lazis.errors import EncryptionUnavailableError

Connection = dbapi2.Connection
DatabaseError = dbapi2.DatabaseError
OperationalError = dbapi2.OperationalError


def connect(path: Path | str) -> Connection:
    # isolation_level=None: autocommit; transactions are explicit (BEGIN IMMEDIATE / COMMIT).
    return sqlcipher3.connect(str(path), isolation_level=None)


def cipher_version(conn: Connection) -> str | None:
    try:
        row = conn.execute("PRAGMA cipher_version").fetchone()
    except DatabaseError:
        return None
    value = row[0] if row else None
    return value if isinstance(value, str) and value else None


def verify_driver() -> tuple[str, str]:
    """Return (cipher_version, sqlite_version) or raise if SQLCipher is not active."""
    conn = connect(":memory:")
    try:
        version = cipher_version(conn)
        if not version:
            raise EncryptionUnavailableError("PRAGMA cipher_version returned nothing")
        sqlite_version = str(conn.execute("SELECT sqlite_version()").fetchone()[0])
        return version, sqlite_version
    finally:
        conn.close()
