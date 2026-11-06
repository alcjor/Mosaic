// Builds small, invented mosaics for the tool tests: the schema of format.sql, rows in
// canonical order (section 3.6: nid = rank of id by UTF-8 bytes, eid = rank of
// (src, type, dst, qualifier), evid = node evidence by nid then edge evidence by eid, ties by
// (sid, locator, ...), xid = rank of (nid, system, kind, locator)), the `search` index filled
// as section 3.2 says and `link_count` as the edges give it. The header's knowledge hash is the
// one the content gives, so every file opens (section 3.8 step 3).
import sqlite3InitModule from "@sqlite.org/sqlite-wasm";
import { FORMAT_SQL } from "../src/format-sql.js";
import { knowledgeHash } from "../src/index.js";

const sqlite3 = await sqlite3InitModule();

/** One evidence row; `source` is a source id (default `doc`). */
export interface EvidenceSpec {
  source?: string;
  locator?: string;
  prop?: string | null;
  method?: "extracted" | "inferred";
  confidence?: number | null;
  producer?: string;
  snippet?: string | null;
  via?: string[] | null;
}

export interface ExternalRefSpec {
  system: string;
  kind: string;
  /** The JSON object, as canonical text (section 3.1). */
  locator: string;
  source?: string;
}

export interface NodeSpec {
  type: string;
  key: string;
  label?: string | null;
  summary?: string | null;
  /** Node props as canonical JSON text, or null. */
  props?: string | null;
  aliases?: string[];
  /** One extracted evidence row per snippet; ignored when `evidence` is given. */
  snippets?: string[];
  evidence?: EvidenceSpec[];
  externalRefs?: ExternalRefSpec[];
}

export interface EdgeSpec {
  type: string;
  /** Node ids, as `<type>:<key>`. */
  from: string;
  to: string;
  qualifier?: string;
  props?: string | null;
  /** Default: one extracted row without a snippet. */
  evidence?: EvidenceSpec[];
}

export interface SourceSpec {
  id: string;
  kind?: "file" | "database" | "knowledge_graph" | "tessera" | "mosaic";
  hash: string;
  notice?: string | null;
}

export interface MosaicSpec {
  nodes: NodeSpec[];
  /** Node types to declare beyond those the nodes use. */
  types?: string[];
  /** Declared props of node types, as canonical JSON text; default `{"name":"text"}`. */
  typeProps?: Record<string, string>;
  /** Edge types to declare, as [name, from, to]. */
  edgeTypes?: [string, string, string][];
  edges?: EdgeSpec[];
  /** Sources beyond `doc` (hash `a…a`), which is always there. */
  sources?: SourceSpec[];
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

/** NULL before any value, then numbers or text. */
function compareValue(a: string | number | null, b: string | number | null): number {
  if (a === b) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return compareUtf8(String(a), String(b));
}

function compareTuple(a: (string | number | null)[], b: (string | number | null)[]): number {
  for (let i = 0; i < a.length; i++) {
    const c = compareValue(a[i]!, b[i]!);
    if (c !== 0) return c;
  }
  return 0;
}

export const DOC_HASH = "a".repeat(64);

interface EvidenceRow {
  nid: number | null;
  eid: number | null;
  prop: string | null;
  sid: number;
  locator: string;
  method: string;
  producer: string;
  confidence: number | null;
  via: string | null;
  snippet: string | null;
}

/** The bytes of a sealed mosaic holding `spec`. */
export function buildMosaic(spec: MosaicSpec): Uint8Array {
  const db = new sqlite3.oo1.DB(":memory:", "c");
  try {
    db.exec(FORMAT_SQL);
    db.exec({
      sql:
        "INSERT INTO header (one, format_version, kind, producer, settings, knowledge_hash, " +
        "pattern_hash, target) VALUES (1, '0.1', 'mosaic', 'kit-test/0.1', '{}', ?, ?, 'test')",
      bind: [DOC_HASH, DOC_HASH],
    });
    const doc: SourceSpec = { id: "doc", kind: "file", hash: DOC_HASH };
    const sources: SourceSpec[] = [doc, ...(spec.sources ?? [])].sort(
      (a, b) => compareUtf8(a.id, b.id),
    );
    const sid = new Map<string, number>();
    sources.forEach((s, i) => {
      sid.set(s.id, i + 1);
      db.exec({
        sql: "INSERT INTO source (sid, id, kind, path, hash, notice) VALUES (?, ?, ?, NULL, ?, ?)",
        bind: [i + 1, s.id, s.kind ?? "file", s.hash, s.notice ?? null],
      });
    });
    const sourceOf = (id: string | undefined): number => {
      const found = sid.get(id ?? "doc");
      if (found === undefined) throw new Error(`no source ${id}`);
      return found;
    };
    const nodeTypes = new Set([...(spec.types ?? []), ...spec.nodes.map((n) => n.type)]);
    for (const t of [...nodeTypes].sort(compareUtf8)) {
      db.exec({
        sql: "INSERT INTO type (name, kind, key_prop, props) VALUES (?, 'node', 'name', ?)",
        bind: [t, spec.typeProps?.[t] ?? '{"name":"text"}'],
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
    const nid = new Map<string, number>();
    nodes.forEach((n, i) => nid.set(n.id, i + 1));
    const nidOf = (id: string): number => {
      const found = nid.get(id);
      if (found === undefined) throw new Error(`no node ${id}`);
      return found;
    };
    const evidenceRow = (subject: { nid: number | null; eid: number | null }, e: EvidenceSpec, j: number): EvidenceRow => {
      const method = e.method ?? "extracted";
      return {
        ...subject,
        prop: e.prop ?? null,
        sid: sourceOf(e.source),
        locator: e.locator ?? `row=${subject.nid ?? subject.eid};entry=${j + 1}`,
        method,
        producer: e.producer ?? "kit-test/0.1",
        confidence: method === "inferred" ? (e.confidence ?? 0.5) : null,
        via: e.via ? JSON.stringify(e.via) : null,
        snippet: e.snippet ?? null,
      };
    };
    const byTies = (a: EvidenceRow, b: EvidenceRow) =>
      compareTuple(
        [a.sid, a.locator, a.prop, a.method, a.producer, a.confidence === null ? null : Math.round(a.confidence * 1e6), a.via],
        [b.sid, b.locator, b.prop, b.method, b.producer, b.confidence === null ? null : Math.round(b.confidence * 1e6), b.via],
      );
    const evidence: EvidenceRow[] = [];
    const refs: { nid: number; system: string; kind: string; locator: string; sid: number }[] = [];
    nodes.forEach((n, i) => {
      const id = i + 1;
      db.exec({
        sql: "INSERT INTO node (nid, id, type, key, label, summary, props) VALUES (?, ?, ?, ?, ?, ?, ?)",
        bind: [id, n.id, n.type, n.key, n.label ?? null, n.summary ?? null, n.props ?? null],
      });
      const aliases = [...(n.aliases ?? [])].sort(compareNocase);
      for (const a of aliases) {
        db.exec({ sql: "INSERT INTO alias (text, nid, origin) VALUES (?, ?, 'source')", bind: [a, id] });
      }
      const specs: EvidenceSpec[] = n.evidence ?? ((n.snippets ?? []).length === 0 ? [{}] : n.snippets!.map((s) => ({ snippet: s })));
      const rows = specs.map((e, j) => evidenceRow({ nid: id, eid: null }, e, j)).sort(byTies);
      evidence.push(...rows);
      const kept = rows.map((r) => r.snippet).filter((s): s is string => s !== null);
      const joined = (values: string[]) => (values.length === 0 ? null : values.join("\n"));
      db.exec({
        sql: "INSERT INTO search (rowid, label, aliases, summary, snippets) VALUES (?, ?, ?, ?, ?)",
        bind: [id, n.label ?? null, joined(aliases), n.summary ?? null, joined(kept)],
      });
      for (const r of n.externalRefs ?? []) {
        refs.push({ nid: id, system: r.system, kind: r.kind, locator: r.locator, sid: sourceOf(r.source) });
      }
    });
    const edges = (spec.edges ?? [])
      .map((e) => ({ ...e, src: nidOf(e.from), dst: nidOf(e.to), qualifier: e.qualifier ?? "" }))
      .sort((a, b) => compareTuple([a.src, a.type, a.dst, a.qualifier], [b.src, b.type, b.dst, b.qualifier]));
    const counts = new Map<string, number>();
    edges.forEach((e, i) => {
      const eid = i + 1;
      db.exec({
        sql: "INSERT INTO edge (eid, type, src, dst, qualifier, props) VALUES (?, ?, ?, ?, ?, ?)",
        bind: [eid, e.type, e.src, e.dst, e.qualifier, e.props ?? null],
      });
      const rows = (e.evidence ?? [{}]).map((ev, j) => evidenceRow({ nid: null, eid }, ev, j)).sort(byTies);
      evidence.push(...rows);
      for (const key of [`${e.src}\u0000${e.type}\u0000out`, `${e.dst}\u0000${e.type}\u0000in`]) {
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
    });
    evidence.forEach((r, i) => {
      db.exec({
        sql:
          "INSERT INTO evidence (evid, nid, eid, prop, sid, locator, method, producer, confidence, via) " +
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        bind: [i + 1, r.nid, r.eid, r.prop, r.sid, r.locator, r.method, r.producer, r.confidence, r.via],
      });
      if (r.snippet !== null) db.exec({ sql: "INSERT INTO snippet (evid, text) VALUES (?, ?)", bind: [i + 1, r.snippet] });
    });
    for (const [key, count] of counts) {
      const [n, type, direction] = key.split("\u0000");
      db.exec({
        sql: "INSERT INTO link_count (nid, type, direction, count) VALUES (?, ?, ?, ?)",
        bind: [Number(n), type!, direction!, count],
      });
    }
    refs
      .sort((a, b) => compareTuple([a.nid, a.system, a.kind, a.locator], [b.nid, b.system, b.kind, b.locator]))
      .forEach((r, i) => {
        db.exec({
          sql: "INSERT INTO external_ref (xid, nid, system, kind, locator, sid) VALUES (?, ?, ?, ?, ?, ?)",
          bind: [i + 1, r.nid, r.system, r.kind, r.locator, r.sid],
        });
      });
    db.exec({ sql: "UPDATE header SET knowledge_hash = ?", bind: [knowledgeHash(db)] });
    return sqlite3.capi.sqlite3_js_db_export(db);
  } finally {
    db.close();
  }
}
