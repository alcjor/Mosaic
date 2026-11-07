/**
 * A single-file export (`mosaic export`, plan M3.8): the page with the mosaic inside, opened
 * offline from `file://` with a double-click (docs/design.md, Implementation plan, Viewer). The
 * export holds, beside the page's own script, one JSON element: the mosaic's name and bytes, the
 * view file's settings (`ViewSettings.as_json`) and SQLite's WebAssembly, the bytes
 * gzip-compressed and then base64. The page unpacks them with the browser's own
 * `DecompressionStream` and asks nothing of a network: the kit opens the bytes by the reading
 * rules, both hashes checked (section 3.8), as it opens any file.
 */
import { parseView, type ViewSettings } from "./view.js";

/** The id of the element that holds an export's data. */
export const EXPORT_ID = "mosaic-export";

export interface Exported {
  readonly name: string;
  readonly mosaic: Uint8Array;
  readonly sqlite: Uint8Array;
  readonly view: ViewSettings;
}

async function bytes(base64: unknown, what: string): Promise<Uint8Array> {
  if (typeof base64 !== "string") throw new Error(`export: ${what} must be base64 text`);
  let text: string;
  try {
    text = atob(base64);
  } catch {
    throw new Error(`export: ${what} is not base64`);
  }
  const packed = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) packed[i] = text.charCodeAt(i);
  try {
    const stream = new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch {
    throw new Error(`export: ${what} is not gzip-compressed`);
  }
}

/** The export's data, from the JSON text of its element; rejects when malformed. */
export async function parseExport(text: string): Promise<Exported> {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("export: its data is not JSON");
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) throw new Error("export: its data must be an object");
  const given = data as Record<string, unknown>;
  if (typeof given.name !== "string" || given.name === "") throw new Error("export: name must be non-empty text");
  const view = parseView(given.view);
  const mosaic = await bytes(given.mosaic, "mosaic"); // one after the other, so the first wrong one is named
  const sqlite = await bytes(given.sqlite, "sqlite");
  return { name: given.name, mosaic, sqlite, view };
}

/** The export the document holds, or null for a page served by `mosaic view` or opened by hand. */
export async function readExport(doc: Pick<Document, "getElementById">): Promise<Exported | null> {
  const element = doc.getElementById(EXPORT_ID);
  return element === null ? null : parseExport(element.textContent ?? "");
}
