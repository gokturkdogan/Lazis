"""Encrypted storage bootstrap: driver check → open → migrate (with pre-migration backup) →
instance identity → on-disk encryption verification → integrity check."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from lazis.config.model import StorageSection
from lazis.observability.logging import get_logger, log_event
from lazis.security.secrets import SecretBytes
from lazis.storage import driver
from lazis.storage.backup import create_snapshot
from lazis.storage.database import Database
from lazis.storage.driver import Connection
from lazis.storage.migrations import Migration, MigrationResult, load_migrations, migrate
from lazis.storage.repositories import ensure_instance_meta, write_audit

_log = get_logger("storage")


@dataclass(frozen=True)
class StorageHandle:
    db: Database
    meta: dict[str, str]
    migration: MigrationResult
    schema_version: int


def open_storage(
    section: StorageSection,
    key: SecretBytes,
    *,
    app_version: str,
    migrations: Sequence[Migration] | None = None,
) -> StorageHandle:
    cipher_version, sqlite_version = driver.verify_driver()
    log_event(
        _log,
        logging.INFO,
        "storage.driver_verified",
        cipher_version=cipher_version,
        sqlite_version=sqlite_version,
    )

    db = Database(section.database_path, key)
    db.open()
    try:
        steps = list(migrations) if migrations is not None else load_migrations("lazis")

        def _backup_before(conn: Connection, current: int, pending: Sequence[Migration]) -> None:
            # Already running in the DB thread (inside migrate): use the connection directly.
            info = create_snapshot(
                conn,
                key,
                section.backup_dir,
                label=f"pre-migration-v{current}",
                keep=section.backups_keep,
            )
            write_audit(
                conn,
                category="backup",
                action="snapshot_created",
                outcome="success",
                reason_code="pre_migration",
                details={
                    "size_bytes": info.size_bytes,
                    "from_version": current,
                    "pending": len(pending),
                },
            )
            log_event(
                _log,
                logging.INFO,
                "storage.pre_migration_backup",
                from_version=current,
                pending=len(pending),
            )

        result = db.run_sync(lambda conn: migrate(conn, steps, before_apply=_backup_before))
        if result.applied:
            log_event(
                _log,
                logging.INFO,
                "storage.migrations_applied",
                versions=list(result.applied),
                current_version=result.current_version,
            )
        else:
            log_event(
                _log, logging.INFO, "storage.schema_current", current_version=result.current_version
            )

        meta = db.run_sync(lambda conn: ensure_instance_meta(conn, app_version=app_version))
        db.assert_encrypted_on_disk()
        db.fix_permissions()
        if section.quick_check_on_startup:
            db.require_healthy()
        log_event(
            _log,
            logging.INFO,
            "storage.ready",
            schema_version=result.current_version,
            encrypted_on_disk=db.verify_encrypted_on_disk(),
        )
        return StorageHandle(
            db=db, meta=meta, migration=result, schema_version=result.current_version
        )
    except BaseException:
        db.close()
        raise
