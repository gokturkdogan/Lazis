-- 0007_quality — Phase 9 (lazis.db). Forward-only: never edit after it has been applied.
-- Phase 9: memory quality checks (ADR-0020). Additive: one table, nothing else changes.
--
-- A suggestion the user dismissed ("Bu öneriyi gizle") is not shown again: the finding's
-- fingerprint (kind + the ids it is about, hashed — no content) and when.
CREATE TABLE memory_quality_dismissed (
    fingerprint  TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    created_at   TEXT NOT NULL
) STRICT;
