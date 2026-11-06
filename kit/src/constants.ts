/**
 * The constants every part of the kit shares (Specification 0.1, sections 3.1, 8 and 8.2).
 */

/** Format version this kit reads (header.format_version). */
export const FORMAT_VERSION = "0.1";

/** PRAGMA application_id of every tessera and mosaic: "MOSA". */
export const APPLICATION_ID = 0x4d4f5341;

/** PRAGMA user_version for format 0.1. */
export const USER_VERSION = 1;

/** The kit's tools; `path` arrives after the first milestone. */
export const TOOLS = ["find", "get", "neighbors", "path", "table", "cite"] as const;

export type ToolName = (typeof TOOLS)[number];

/** Length limits for text read from a file (section 8.2). */
export const TEXT_LIMITS = { label: 120, summary: 400, snippet: 600 } as const;

/** Marker appended when text is cut. */
export const CUT_MARKER = "…";

/** Cut text read from a file to `limit` characters, adding the marker when cut. */
export function cut(text: string, limit: number): string {
  const chars = Array.from(text);
  return chars.length <= limit ? text : chars.slice(0, limit).join("") + CUT_MARKER;
}
