/**
 * Tool answers (Specification 0.1, sections 8.1, 8.2 and 8.5; `spec/answers.schema.json`).
 *
 * Every answer is an object with the tool's name, the mosaic's knowledge hash and either `data`,
 * which holds everything read from the file, or `error`. An error's message names what failed in
 * the caller's words and the kit's, never in text read from the file: that text belongs in
 * `data` only (section 8.2).
 */
import type { ToolName } from "./constants.js";

/** How a `find` result matched (section 8.5). */
export type Match = "exact" | "text" | "vector";

export interface FindResult {
  readonly id: string;
  readonly type: string;
  /** The node's label, cut at 120 characters with the marker; null when it has none. */
  readonly label: string | null;
  readonly match: Match;
}

export interface FindAnswer {
  readonly tool: "find";
  /** The knowledge hash of the mosaic answered from. */
  readonly mosaic: string;
  readonly data: { readonly results: readonly FindResult[]; readonly total: number };
}

export interface GetData {
  readonly id: string;
  readonly type: string;
  /** Cut at 120 characters with the marker; null when the node has none. */
  readonly label: string | null;
  /** Cut at 400 characters with the marker; null when the node has none. */
  readonly summary: string | null;
  /** The node's property object, text values cut at 400 characters; null when it has none. */
  readonly props: Readonly<Record<string, unknown>> | null;
  /** At most 20, in alias order, each cut at 120 characters. */
  readonly aliases: readonly string[];
  /** How many aliases the node has. */
  readonly aliases_total: number;
  readonly external_refs: readonly {
    readonly system: string;
    readonly kind: string;
    readonly locator: Readonly<Record<string, unknown>>;
  }[];
  /** Edges per edge type and direction. */
  readonly links: readonly { readonly edge: string; readonly direction: "out" | "in"; readonly count: number }[];
}

export interface GetAnswer {
  readonly tool: "get";
  readonly mosaic: string;
  readonly data: GetData;
}

/** One evidence row as `cite` gives it. */
export interface CiteEvidence {
  /** The source's id. */
  readonly source: string;
  readonly source_hash: string;
  readonly locator: string;
  readonly method: "extracted" | "inferred";
  /** Present exactly on inferred rows. */
  readonly confidence: number | null;
  /** Cut at 600 characters with the marker; null when the file keeps none. */
  readonly snippet: string | null;
  /** The knowledge hashes of the mosaics the evidence passed through, innermost first. */
  readonly via?: readonly string[];
}

export interface CiteAnswer {
  readonly tool: "cite";
  readonly mosaic: string;
  readonly data: {
    /** The node's id, or the edge as from, type and to. */
    readonly subject: string | { readonly from: string; readonly type: string; readonly to: string };
    readonly evidence: readonly CiteEvidence[];
    readonly total: number;
  };
}

/** The error codes of `answers.schema.json`. */
export type ErrorCode =
  | "unknown_id"
  | "unknown_type"
  | "unknown_edge"
  | "unknown_column"
  | "bad_argument"
  | "limit_exceeded";

export interface ErrorAnswer {
  readonly tool: ToolName;
  readonly mosaic: string;
  readonly error: {
    readonly code: ErrorCode;
    readonly message: string;
    /** The closest ids, for an unknown id (section 8.1); at most 5. */
    readonly suggestions: readonly string[];
  };
}

export type Answer = FindAnswer | GetAnswer | CiteAnswer | ErrorAnswer;

/** The longest error message `answers.schema.json` allows. */
const MESSAGE_LIMIT = 400;

/** A failed tool call: the tool turns it into an {@link ErrorAnswer}. */
export class ToolError extends Error {
  override readonly name = "ToolError";

  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly suggestions: readonly string[] = [],
  ) {
    super(message);
  }
}

export function errorAnswer(tool: ToolName, mosaic: string, e: ToolError): ErrorAnswer {
  const chars = Array.from(e.message);
  const message = chars.length <= MESSAGE_LIMIT ? e.message : chars.slice(0, MESSAGE_LIMIT - 1).join("") + "…";
  return { tool, mosaic, error: { code: e.code, message, suggestions: e.suggestions.slice(0, 5) } };
}

/** A caller's argument as an error message shows it: quoted, and short. */
export function shownArgument(value: unknown): string {
  const text = typeof value === "string" ? JSON.stringify(value) : String(value);
  const chars = Array.from(text);
  return chars.length <= 60 ? text : chars.slice(0, 60).join("") + "…";
}
