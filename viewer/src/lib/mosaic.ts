/**
 * What the viewer asks the kit (Specification 0.1, sections 8.1 and 8.2). The kit runs inside
 * the page: the mosaic's bytes are opened by `openFile`, which checks the reading rules (section
 * 3.8), and every view below is built from tool answers alone, so the page shows nothing the
 * tools would not give an agent. No query server is involved.
 */
import {
  openFile,
  type CiteEvidence,
  type ErrorAnswer,
  type FindResult,
  type GetData,
  type Match,
  type NeighborEdge,
  type SealedFile,
} from "@mosaic/kit";

/** The query parameter that names a mosaic for the page to fetch when it opens. */
export const MOSAIC_PARAM = "mosaic";

/** How each `find` tier is named on screen (brand book, section 6: ResultRow). */
export const TIER_NAMES: Readonly<Record<Match, string>> = { exact: "Exact", text: "Text", vector: "Similar" };

/** The tiers in the order `find` lists them (section 8.5). */
const TIERS: readonly Match[] = ["exact", "text", "vector"];

/** A tool's error, as the page shows it: the kit's message and the closest ids it names. */
export interface ToolFailure {
  readonly message: string;
  readonly suggestions: readonly string[];
}

export interface ResultGroup {
  readonly match: Match;
  readonly results: readonly FindResult[];
}

export interface SearchView {
  readonly query: string;
  /** Results grouped by tier, in `find`'s order; tiers with no result are left out. */
  readonly groups: readonly ResultGroup[];
  /** How many results `find` counted; the list holds at most 20. */
  readonly total: number;
}

/** The edges of one edge type and direction, as `neighbors` gives them. */
export interface LinkGroup {
  readonly edge: string;
  readonly direction: "out" | "in";
  /** How many edges of this type and direction the node has (`get`'s link count). */
  readonly count: number;
  /** At most 20, each with the other node's id and label. */
  readonly edges: readonly NeighborEdge[];
}

export interface NodeView {
  readonly node: GetData;
  readonly links: readonly LinkGroup[];
  /** The node's evidence from `cite`, at most 20, and how many rows it has. */
  readonly sources: readonly CiteEvidence[];
  readonly sourcesTotal: number;
}

function failure(answer: ErrorAnswer): ToolFailure {
  return { message: answer.error.message, suggestions: answer.error.suggestions };
}

/** Open a mosaic's bytes with the kit, in the page; a file the reading rules refuse throws. */
export function openMosaic(bytes: Uint8Array, name: string): Promise<SealedFile> {
  return openFile(bytes, name);
}

/** The mosaic the page's address names with `?mosaic=<url>`, fetched as bytes, or null. */
export async function fetchNamedMosaic(
  search: string,
  base: string,
  fetcher: typeof fetch = fetch,
): Promise<{ bytes: Uint8Array; name: string } | null> {
  const named = new URLSearchParams(search).get(MOSAIC_PARAM);
  if (named === null || named === "") return null;
  const url = new URL(named, base);
  const response = await fetcher(url);
  if (!response.ok) throw new Error(`could not fetch ${named}: ${response.status} ${response.statusText}`.trim());
  const name = decodeURIComponent(url.pathname.split("/").pop() ?? "") || named;
  return { bytes: new Uint8Array(await response.arrayBuffer()), name };
}

/** `find` on `query`, its results grouped by tier. */
export async function search(file: SealedFile, query: string): Promise<SearchView | ToolFailure> {
  const answer = await file.find({ query });
  if ("error" in answer) return failure(answer);
  const groups = TIERS.map((match) => ({ match, results: answer.data.results.filter((r) => r.match === match) })).filter(
    (g) => g.results.length > 0,
  );
  return { query, groups, total: answer.data.total };
}

/** A node's page: `get`, then `neighbors` for each edge type and direction it has, then `cite`. */
export async function nodePage(file: SealedFile, id: string): Promise<NodeView | ToolFailure> {
  const got = await file.get({ id });
  if ("error" in got) return failure(got);
  const links: LinkGroup[] = [];
  for (const link of got.data.links) {
    const answer = await file.neighbors({ id, edge: link.edge, direction: link.direction });
    if ("error" in answer) return failure(answer);
    links.push({ edge: link.edge, direction: link.direction, count: link.count, edges: answer.data.edges });
  }
  const cited = await file.cite({ id });
  if ("error" in cited) return failure(cited);
  return { node: got.data, links, sources: cited.data.evidence, sourcesTotal: cited.data.total };
}

/** The first 12 characters of a knowledge hash, as the card names a mosaic (section 8.5). */
export function shortHash(hash: string): string {
  return hash.slice(0, 12);
}
