-- lazis:foreign-keys=off
-- 0005_graph — Phase 7: entity and relationship graph (lazis.db). ADR-0016.
-- Forward-only. Never edit after it has been applied anywhere; add 0006_* instead.
--
-- The first line makes the runner apply this with foreign keys off and check
-- `PRAGMA foreign_key_check` before committing (SQLite's table-rebuild procedure):
-- `memory_entities` is rebuilt to allow the new kinds, and dropping it with foreign keys on
-- would cascade-delete every memory. No row is lost or changed: all columns are copied.

CREATE TABLE memory_entities_new (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL
                  CHECK (kind IN ('person', 'project', 'organization', 'place', 'event', 'group', 'thing')),
    name          TEXT NOT NULL,
    name_key      TEXT NOT NULL,
    relation      TEXT,                       -- display label of the relation to the user
    relation_key  TEXT,
    description   TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged')),
    merged_into   TEXT REFERENCES memory_entities(id),
    is_user       INTEGER NOT NULL DEFAULT 0 CHECK (is_user IN (0, 1)),
    confidence    REAL NOT NULL DEFAULT 0.85,
    origin        TEXT NOT NULL DEFAULT 'stated'
                  CHECK (origin IN ('stated', 'requested', 'confirmed', 'imported', 'user_edit', 'system')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
) STRICT;
INSERT INTO memory_entities_new (id, kind, name, name_key, relation, relation_key, description,
                                 status, merged_into, created_at, updated_at)
    SELECT id, kind, name, name_key, relation, relation_key, description, status, merged_into,
           created_at, updated_at
    FROM memory_entities;
DROP TABLE memory_entities;
ALTER TABLE memory_entities_new RENAME TO memory_entities;
CREATE INDEX ix_memory_entities_key ON memory_entities(name_key, status);
CREATE INDEX ix_memory_entities_kind ON memory_entities(kind, status, updated_at);
CREATE UNIQUE INDEX ux_memory_entities_user ON memory_entities(is_user) WHERE is_user = 1;

-- The user, as a relationship endpoint ("user → çocukluk arkadaşı → Ahmet"). Memories about
-- the user keep subject_id NULL (Phase 6). Never listed, resolved, merged or forgotten.
INSERT INTO memory_entities (id, kind, name, name_key, status, is_user, confidence, origin,
                             created_at, updated_at)
    VALUES ('user', 'person', 'Kullanıcı', '__user__', 'active', 1, 1.0, 'system',
            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

-- One stated relationship, stored once (source → target). Inverse and symmetric readings are
-- computed from the vocabulary (lazis.memory.relations) at query time, never stored, so a
-- corrected or forgotten edge leaves no derived edges behind.
-- Reads "target is source's <type>" (roles) or "source <verb> target" (affiliations).
CREATE TABLE memory_relationships (
    id                    TEXT PRIMARY KEY,
    source_id             TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    type                  TEXT NOT NULL,
    target_id             TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    qualifier             TEXT,              -- the user's own words when they refine the type
    status                TEXT NOT NULL
                          CHECK (status IN ('active', 'ended', 'planned', 'unverified', 'superseded', 'retracted')),
    origin                TEXT NOT NULL
                          CHECK (origin IN ('stated', 'requested', 'confirmed', 'imported', 'user_edit', 'migrated')),
    confidence            REAL NOT NULL,
    sensitivity           TEXT NOT NULL DEFAULT 'normal'
                          CHECK (sensitivity IN ('normal', 'personal', 'sensitive')),
    sensitivity_category  TEXT,
    time_text             TEXT,              -- when, as the user said it ("geçen yıl"); never invented
    valid_from            TEXT,
    valid_to              TEXT,
    supersedes_id         TEXT REFERENCES memory_relationships(id) ON DELETE SET NULL,
    conflict_state        TEXT NOT NULL DEFAULT 'none' CHECK (conflict_state IN ('none', 'pending')),
    change_set_id         TEXT NOT NULL REFERENCES change_sets(id),
    version               INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    CHECK (source_id != target_id)
) STRICT;
CREATE INDEX ix_relationships_source ON memory_relationships(source_id, status, type);
CREATE INDEX ix_relationships_target ON memory_relationships(target_id, status, type);

CREATE TABLE memory_relationship_evidence (
    id               TEXT PRIMARY KEY,
    relationship_id  TEXT NOT NULL REFERENCES memory_relationships(id) ON DELETE CASCADE,
    source_type      TEXT NOT NULL CHECK (source_type IN ('message', 'import', 'user_edit', 'confirmation', 'migration')),
    source_ref       TEXT,
    quote            TEXT,
    created_at       TEXT NOT NULL
) STRICT;
CREATE INDEX ix_relationship_evidence ON memory_relationship_evidence(relationship_id);
CREATE INDEX ix_relationship_evidence_source ON memory_relationship_evidence(source_ref);

-- "These are different people": never merged, never resolved as one (stored with a < b).
CREATE TABLE memory_entity_distinctions (
    entity_a    TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    entity_b    TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (entity_a, entity_b),
    CHECK (entity_a < entity_b)
) STRICT;
