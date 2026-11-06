// Builds small, invented mosaics for the tool tests: the schema of format.sql, nodes in
// canonical order (nid = rank of id by UTF-8 bytes, section 3.6), one evidence row per snippet
// (or one without a snippet), and the `search` index filled as section 3.2 says. The header's
// knowledge hash is the one the content gives, so every file opens (section 3.8 step 3).
import sqlite3InitModule from "@sqlite.org/sqlite-wasm";
import { FORMAT_SQL } from "../src/format-sql.js";
import { knowledgeHash } from "../src/index.js";

const sqlite3 = await sqlite3InitModule();

export interface NodeSpec {
  type: string;
  key: string;
  label?: string | null;
  summary?: string | null;
  aliases?: string[];
  snippets?: string[];
}

export interface MosaicSpec {
  nodes: NodeSpec[];
  /** Node types to declare beyond those the nodes use. */
  types?: string[];
  /** Edge types to declare, as [name, from, to]. */
  edgeTypes?: [string, string, string][];
}

const encoder = new TextEncoder();

/** Order by UTF-8 bytes, as the specification compares text. */
export function compareUtf8(a: string, b: string): number {
  const x = encoder.encode(a);
  const y = encoder.encode(b);
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) if (x[i] !== y[i]) return x[i]! - y[i]!;
  return x.length - y.length;
}

/** Case-insensitive for ASCII letters only, as SQLite's NOCASE, then by UTF-8 bytes. */
function compareNocase(a: string, b: string): number {
  const fold = (s: string) => s.replace(/[A-Z]/g, (c) => c.toLowerCase());
  return compareUtf8(fold(a), fold(b));
}

const HASH = "a".repeat(64);

/** The bytes of a sealed mosaic holding `spec`. */
export function buildMosaic(spec: MosaicSpec): Uint8Array {
  const db = new sqlite3.oo1.DB(":memory:", "c");
  try {
    db.exec(FORMAT_SQL);
    db.exec({
      sql:
        "INSERT INTO header (one, format_version, kind, producer, settings, knowledge_hash, " +
        "pattern_hash, target) VALUES (1, '0.1', 'mosaic', 'kit-test/0.1', '{}', ?, ?, 'test')",
      bind: [HASH, HASH],
    });
    db.exec({
      sql: "INSERT INTO source (sid, id, kind, path, hash, notice) VALUES (1, 'doc', 'file', 'doc.txt', ?, NULL)",
      bind: [HASH],
    });
    const nodeTypes = new Set([...(spec.types ?? []), ...spec.nodes.map((n) => n.type)]);
    for (const t of [...nodeTypes].sort(compareUtf8)) {
      db.exec({
        sql: "INSERT INTO type (name, kind, key_prop, props) VALUES (?, 'node', 'name', '{\"name\":\"text\"}')",
        bind: [t],
      });
    }
    for (const [name, from, to] of spec.edgeTypes ?? []) {
      db.exec({
        sql: "INSERT INTO type (name, kind, from_type, to_type) VALUES (?, 'edge', ?, ?)",
        bind: [name, from, to],
      });
    }
    const nodes = spec.nodes
      .map((n) => ({ ...n, id: `${n.type}:${n.key}` }))
      .sort((a, b) => compareUtf8(a.id, b.id));
    let evid = 0;
    nodes.forEach((n, i) => {
      const nid = i + 1;
      db.exec({
        sql: "INSERT INTO node (nid, id, type, key, label, summary, props) VALUES (?, ?, ?, ?, ?, ?, NULL)",
        bind: [nid, n.id, n.type, n.key, n.label ?? null, n.summary ?? null],
      });
      const aliases = [...(n.aliases ?? [])].sort(compareNocase);
      for (const a of aliases) {
        db.exec({ sql: "INSERT INTO alias (text, nid, origin) VALUES (?, ?, 'source')", bind: [a, nid] });
      }
      const snippets = n.snippets ?? [];
      const rows = snippets.length === 0 ? [null] : snippets;
      rows.forEach((text, j) => {
        evid += 1;
        db.exec({
          sql:
            "INSERT INTO evidence (evid, nid, sid, locator, method, producer) " +
            "VALUES (?, ?, 1, ?, 'extracted', 'kit-test/0.1')",
          bind: [evid, nid, `row=${nid};entry=${j + 1}`],
        });
        if (text !== null) db.exec({ sql: "INSERT INTO snippet (evid, text) VALUES (?, ?)", bind: [evid, text] });
      });
      const joined = (values: string[]) => (values.length === 0 ? null : values.join("\n"));
      db.exec({
        sql: "INSERT INTO search (rowid, label, aliases, summary, snippets) VALUES (?, ?, ?, ?, ?)",
        bind: [nid, n.label ?? null, joined(aliases), n.summary ?? null, joined(snippets)],
      });
    });
    db.exec({ sql: "UPDATE header SET knowledge_hash = ?", bind: [knowledgeHash(db)] });
    return sqlite3.capi.sqlite3_js_db_export(db);
  } finally {
    db.close();
  }
}
