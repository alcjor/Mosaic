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

export type Answer = FindAnswer | ErrorAnswer;

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
