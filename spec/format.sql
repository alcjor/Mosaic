-- Mosaic file format 0.1 (DRAFT) — normative schema for tesserae and mosaics.
--
-- Status: draft 0.1, written from Part 5 of docs/design.md (Specification 0.1,
-- sections 3.1 to 3.10). Where this file and the specification disagree, this
-- file wins for structure and the specification wins for meaning; the
-- disagreement is a defect to fix.
--
-- A file is one SQLite 3 database with no journal or WAL beside it, page size
-- 4096, containing exactly the objects below (plus SQLite's internal tables and
-- optionally sqlite_stat1). Readers MUST support FTS5.
--
-- ---------------------------------------------------------------------------
-- CANONICAL ORDER (section 3.6)
-- ---------------------------------------------------------------------------
-- Integer row ids are dense (1..n) and follow content order. Text compares by
-- its UTF-8 bytes (BINARY) unless a column declares another collation; NULL
-- sorts before any value.
--
--   source        sid   = rank of id
--   node          nid   = rank of id
--   edge          eid   = rank of (src, type, dst, qualifier)
--   evidence      evid  = node evidence ordered by nid, then edge evidence
--                         ordered by eid; ties by (sid, locator, prop, method,
--                         producer, confidence, via), confidence compared as
--                         CAST(round(confidence*1000000) AS INTEGER)
--   mention       mid   = rank of (nid, locator)
--   external_ref  xid   = rank of (nid, system, kind, locator)
--
-- ---------------------------------------------------------------------------
-- KNOWLEDGE HASH (section 3.6)
-- ---------------------------------------------------------------------------
-- SHA-256 (64 lowercase hex characters) of a byte string built from these
-- parts, in this order:
--
--   part          columns, in order                                   row order
--   header        format_version, kind                                the one row
--   source        sid, id, kind, hash, notice                         sid
--   type          name, kind, description, key_prop, from_type,
--                 to_type, props                                      name
--   node          nid, id, type, key, label, summary, props           nid
--   edge          eid, type, src, dst, qualifier, props               eid
--   alias         text, nid, origin                                   text COLLATE NOCASE, then nid
--   evidence      evid, nid, eid, prop, sid, locator, method,
--                 producer, confidence, via                           evid
--   snippet       evid, text                                          evid
--   mention       mid, text, locator, nid, role, kind                 mid
--   source_text   sid, text                                           sid
--   external_ref  xid, nid, system, kind, locator, sid                xid
--
-- Each part starts with '#', the part name and a newline (0x0A). Each row is
-- its column values encoded as SQLite's quote() would, joined by ',', followed
-- by a newline: NULL as NULL, integers in decimal, text in single quotes with
-- inner quotes doubled, blobs as X'<uppercase hex>'. The column `confidence`
-- is encoded as quote(CAST(round(confidence*1000000) AS INTEGER)).
-- link_count and search are derived and not hashed; a checker verifies them.
--
-- ---------------------------------------------------------------------------
-- VECTOR HASH (section 3.7)
-- ---------------------------------------------------------------------------
-- SHA-256 of the 48-byte `bits` values of `vector`, concatenated in nid order.
-- ---------------------------------------------------------------------------

PRAGMA application_id = 1297044289;  -- 0x4D4F5341, "MOSA"
PRAGMA user_version = 1;             -- format 0.1
PRAGMA page_size = 4096;
PRAGMA foreign_keys = ON;

-- One row describing the file (section 3.3).
CREATE TABLE header (
    one            INTEGER PRIMARY KEY CHECK (one = 1),
    format_version TEXT NOT NULL CHECK (format_version = '0.1'),
    kind           TEXT NOT NULL CHECK (kind IN ('tessera', 'mosaic')),
    producer       TEXT NOT NULL CHECK (producer GLOB '?*/?*'),
    settings       TEXT NOT NULL DEFAULT '{}'
                   CHECK (json_valid(settings) AND json_type(settings) = 'object'),
    knowledge_hash TEXT NOT NULL
                   CHECK (length(knowledge_hash) = 64 AND knowledge_hash NOT GLOB '*[^0-9a-f]*'),
    vector_hash    TEXT
                   CHECK (vector_hash IS NULL OR (length(vector_hash) = 64 AND vector_hash NOT GLOB '*[^0-9a-f]*')),
    embed_model    TEXT CHECK (embed_model IS NULL OR embed_model GLOB '?*@?*'),
    pattern_hash   TEXT
                   CHECK (pattern_hash IS NULL OR (length(pattern_hash) = 64 AND pattern_hash NOT GLOB '*[^0-9a-f]*')),
    target         TEXT,
    ai_model       TEXT,
    -- vector hash and embedding model come together
    CHECK ((vector_hash IS NULL) = (embed_model IS NULL)),
    -- profile rules
    CHECK (kind = 'mosaic' OR (vector_hash IS NULL AND pattern_hash IS NULL AND target IS NULL)),
    CHECK (kind = 'tessera' OR (pattern_hash IS NOT NULL AND target IS NOT NULL AND ai_model IS NULL))
);

-- Sources (tessera: exactly one) or pieces (mosaic: one per piece).
-- `path` is informative and not hashed, so moving a file does not change identity.
CREATE TABLE source (
    sid    INTEGER PRIMARY KEY,
    id     TEXT NOT NULL UNIQUE,
    kind   TEXT NOT NULL CHECK (kind IN ('file', 'database', 'knowledge_graph', 'tessera', 'mosaic')),
    path   TEXT,
    hash   TEXT NOT NULL CHECK (length(hash) = 64 AND hash NOT GLOB '*[^0-9a-f]*'),
    notice TEXT
);

-- Declared node and edge types (section 3.4).
CREATE TABLE type (
    name        TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('node', 'edge')),
    description TEXT,
    key_prop    TEXT,
    from_type   TEXT REFERENCES type (name),
    to_type     TEXT REFERENCES type (name),
    props       TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(props) AND json_type(props) = 'object'),
    CHECK (
        (kind = 'node' AND name GLOB '[A-Z]*' AND name NOT GLOB '*[^A-Za-z0-9]*'
                       AND from_type IS NULL AND to_type IS NULL)
     OR (kind = 'edge' AND name GLOB '[a-z]*' AND name NOT GLOB '*[^a-z0-9_]*'
                       AND key_prop IS NULL AND from_type IS NOT NULL AND to_type IS NOT NULL)
    )
);

-- Nodes. In a mosaic, id = '<type>:<key>' (checker-enforced, invariant 10).
CREATE TABLE node (
    nid     INTEGER PRIMARY KEY,
    id      TEXT NOT NULL UNIQUE,
    type    TEXT NOT NULL REFERENCES type (name),
    key     TEXT NOT NULL,
    label   TEXT,
    summary TEXT,
    props   TEXT CHECK (props IS NULL OR (json_valid(props) AND json_type(props) = 'object')),
    UNIQUE (type, key)
);

-- Edges. The UNIQUE constraint doubles as the outgoing index.
CREATE TABLE edge (
    eid       INTEGER PRIMARY KEY,
    type      TEXT NOT NULL REFERENCES type (name),
    src       INTEGER NOT NULL REFERENCES node (nid),
    dst       INTEGER NOT NULL REFERENCES node (nid),
    qualifier TEXT NOT NULL DEFAULT '',
    props     TEXT CHECK (props IS NULL OR (json_valid(props) AND json_type(props) = 'object')),
    UNIQUE (src, type, dst, qualifier)
);
CREATE INDEX edge_in ON edge (dst, type);

-- Other names a node goes by; case-insensitive.
CREATE TABLE alias (
    text   TEXT NOT NULL COLLATE NOCASE,
    nid    INTEGER NOT NULL REFERENCES node (nid),
    origin TEXT NOT NULL CHECK (origin IN ('source', 'pattern', 'proposal')),
    PRIMARY KEY (text, nid)
) WITHOUT ROWID;
CREATE INDEX alias_node ON alias (nid);

-- Provenance: exactly one subject; confidence exactly on inferred rows (section 3.5).
-- No two rows are equal in all of (nid, eid, prop, sid, locator, method, producer,
-- confidence, via), NULL equal to NULL and confidence compared as hashed. UNIQUE
-- cannot say this (it treats NULLs as distinct), so the checker verifies it.
CREATE TABLE evidence (
    evid       INTEGER PRIMARY KEY,
    nid        INTEGER REFERENCES node (nid),
    eid        INTEGER REFERENCES edge (eid),
    prop       TEXT,
    sid        INTEGER NOT NULL REFERENCES source (sid),
    locator    TEXT NOT NULL CHECK (locator <> ''),
    method     TEXT NOT NULL CHECK (method IN ('extracted', 'inferred')),
    producer   TEXT NOT NULL,
    confidence REAL,
    via        TEXT CHECK (via IS NULL OR (json_valid(via) AND json_type(via) = 'array')),
    CHECK ((nid IS NULL) <> (eid IS NULL)),
    CHECK ((method = 'extracted' AND confidence IS NULL)
        OR (method = 'inferred' AND confidence IS NOT NULL AND confidence BETWEEN 0 AND 1))
);
CREATE INDEX evidence_node ON evidence (nid) WHERE nid IS NOT NULL;
CREATE INDEX evidence_edge ON evidence (eid) WHERE eid IS NOT NULL;

-- The source passage behind an evidence row (snippets and full text tiers).
CREATE TABLE snippet (
    evid INTEGER PRIMARY KEY REFERENCES evidence (evid),
    text TEXT NOT NULL
);

-- Mentions for link rules; tessera only (section 4.2).
CREATE TABLE mention (
    mid     INTEGER PRIMARY KEY,
    text    TEXT NOT NULL,
    locator TEXT NOT NULL UNIQUE,
    nid     INTEGER NOT NULL REFERENCES node (nid),
    role    TEXT NOT NULL CHECK (role GLOB '?*.?*'),
    kind    TEXT NOT NULL CHECK (kind IN ('identifier', 'phrase'))
);

-- Edges per node, type and direction; mosaic only; derived, not hashed.
CREATE TABLE link_count (
    nid       INTEGER NOT NULL REFERENCES node (nid),
    type      TEXT NOT NULL REFERENCES type (name),
    direction TEXT NOT NULL CHECK (direction IN ('out', 'in')),
    count     INTEGER NOT NULL CHECK (count > 0),
    PRIMARY KEY (nid, type, direction)
) WITHOUT ROWID;

-- One 384-bit sign vector per node; mosaic only, optional (sections 3.7, 6).
CREATE TABLE vector (
    nid  INTEGER PRIMARY KEY REFERENCES node (nid),
    bits BLOB NOT NULL CHECK (typeof(bits) = 'blob' AND length(bits) = 48)
);

-- Contentless full-text index, one row per node with rowid = nid.
-- Tokens keep '-', '_' and '.', so TEMP-3 and PARAM_X stay whole; positions
-- are kept for phrase search; no prefix index. Derived, not hashed.
CREATE VIRTUAL TABLE search USING fts5 (
    label, aliases, summary, snippets,
    content = '',
    tokenize = "unicode61 tokenchars '-_.'"
);

-- Entire text of each text source; full text tier only.
CREATE TABLE source_text (
    sid  INTEGER PRIMARY KEY REFERENCES source (sid),
    text TEXT NOT NULL
);

-- Keys into data that stays outside (section 3.10). No credentials.
CREATE TABLE external_ref (
    xid     INTEGER PRIMARY KEY,
    nid     INTEGER NOT NULL REFERENCES node (nid),
    system  TEXT NOT NULL CHECK (system GLOB '[a-z]*' AND system NOT GLOB '*[^a-z0-9_-]*'),
    kind    TEXT NOT NULL,
    locator TEXT NOT NULL CHECK (json_valid(locator) AND json_type(locator) = 'object'),
    sid     INTEGER NOT NULL REFERENCES source (sid),
    UNIQUE (nid, system, kind, locator)
);

-- Views: text ids only; internal row ids never leave the file.
CREATE VIEW v_node AS
SELECT n.id, n.type, n.key, n.label, n.summary, n.props
FROM node AS n;

CREATE VIEW v_edge AS
SELECT e.type, s.id AS src, d.id AS dst, e.qualifier, e.props
FROM edge AS e
JOIN node AS s ON s.nid = e.src
JOIN node AS d ON d.nid = e.dst;

CREATE VIEW v_alias AS
SELECT a.text, n.id AS node, a.origin
FROM alias AS a
JOIN node AS n ON n.nid = a.nid;

CREATE VIEW v_evidence AS
SELECT
    n.id         AS node,
    es.id        AS edge_src,
    e.type       AS edge_type,
    ed.id        AS edge_dst,
    e.qualifier  AS edge_qualifier,
    v.prop,
    src.id       AS source,
    src.hash     AS source_hash,
    v.locator,
    v.method,
    v.producer,
    v.confidence,
    v.via,
    sn.text      AS snippet
FROM evidence AS v
JOIN source AS src ON src.sid = v.sid
LEFT JOIN node AS n ON n.nid = v.nid
LEFT JOIN edge AS e ON e.eid = v.eid
LEFT JOIN node AS es ON es.nid = e.src
LEFT JOIN node AS ed ON ed.nid = e.dst
LEFT JOIN snippet AS sn ON sn.evid = v.evid;
