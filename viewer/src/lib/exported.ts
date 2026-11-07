/**
 * A single-file export (`mosaic export`, plan M3.8): the page with the mosaic inside, opened
 * offline from `file://` with a double-click (docs/design.md, Implementation plan, Viewer). The
 * export holds, beside the page's own script, one JSON element: the mosaic's name and bytes, the
 * view file's settings (`ViewSettings.as_json`) and SQLite's WebAssembly, the bytes in base64. The
 * page reads them from the document and asks nothing of a network: the kit opens the bytes by the
 * reading rules, both hashes checked (section 3.8), as it opens any file.
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

function bytes(base64: unknown, what: string): Uint8Array {
  if (typeof base64 !== "string") throw new Error(`export: ${what} must be base64 text`);
  let text: string;
  try {
    text = atob(base64);
  } catch {
    throw new Error(`export: ${what} is not base64`);
  }
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) out[i] = text.charCodeAt(i);
  return out;
}

/** The export's data, from the JSON text of its element; throws when malformed. */
export function parseExport(text: string): Exported {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("export: its data is not JSON");
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) throw new Error("export: its data must be an object");
  const given = data as Record<string, unknown>;
  if (typeof given.name !== "string" || given.name === "") throw new Error("export: name must be non-empty text");
  return { name: given.name, mosaic: bytes(given.mosaic, "mosaic"), sqlite: bytes(given.sqlite, "sqlite"), view: parseView(given.view) };
}

/** The export the document holds, or null for a page served by `mosaic view` or opened by hand. */
export function readExport(doc: Pick<Document, "getElementById">): Exported | null {
  const element = doc.getElementById(EXPORT_ID);
  return element === null ? null : parseExport(element.textContent ?? "");
}
