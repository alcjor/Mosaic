/**
 * A single-file export (`mosaic export`, plan M3.8): the page with the mosaic inside, opened
 * offline from `file://` with a double-click (docs/design.md, Implementation plan, Viewer). The
 * export holds, beside the page's own script, one JSON element: the mosaic's name and bytes, the
 * view file's settings (`ViewSettings.as_json`) and SQLite's WebAssembly, the bytes
 * gzip-compressed and then base64. The page unpacks them with the browser's own
 * `DecompressionStream` and asks nothing of a network: the kit opens the bytes by the reading
 * rules, both hashes checked (section 3.8), as it opens any file.
 *
 * An export with `search: semantic` (plan M3.9) also holds the embedding model's two files and
 * ONNX Runtime: its module's text and its WebAssembly. The page imports the module from a blob
 * (a page opened from `file://` cannot import a file) and gives the kit both; the kit checks the
 * model's files by their pinned hashes (section 6) before it runs them.
 */
import type { ModelFiles, OrtModule, Piece, Runtime } from "@mosaic/kit";
import { parseView, type ViewSettings } from "./view.js";

/** The id of the element that holds an export's data. */
export const EXPORT_ID = "mosaic-export";

export interface Exported {
  readonly name: string;
  readonly mosaic: Uint8Array;
  readonly sqlite: Uint8Array;
  readonly view: ViewSettings;
  /** The embedding model's files and ONNX Runtime, in an export with `search: semantic`. */
  readonly model: { readonly files: ModelFiles; readonly ortModule: Uint8Array; readonly ortWasm: Uint8Array } | null;
}

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`export: ${what} must be an object`);
  return value as Record<string, unknown>;
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
  let model: Exported["model"] = null;
  if (given.model !== undefined || given.ort !== undefined) {
    const files = record(given.model, "model");
    const ort = record(given.ort, "ort");
    model = {
      files: { model: await bytes(files.model, "model.model"), tokenizer: await bytes(files.tokenizer, "model.tokenizer") },
      ortModule: await bytes(ort.module, "ort.module"),
      ortWasm: await bytes(ort.wasm, "ort.wasm"),
    };
  }
  return { name: given.name, mosaic, sqlite, view, model };
}

/**
 * The mosaic an export's file was cut from (answer on #140), when its pieces are exactly one
 * mosaic, as `mosaic export` builds a cut with `export.types`; else null. The page shows it as
 * "from <piece> <short hash>", read from the file itself.
 */
export function cutFrom(pieces: readonly Piece[]): Piece | null {
  return pieces.length === 1 && pieces[0]!.kind === "mosaic" ? pieces[0]! : null;
}

/** ONNX Runtime from an export: its module imported from a blob, and its WebAssembly's bytes. */
export async function runtimeOf(model: NonNullable<Exported["model"]>): Promise<Runtime> {
  const text = new TextDecoder("utf-8", { fatal: true }).decode(model.ortModule);
  const url = URL.createObjectURL(new Blob([text], { type: "text/javascript" }));
  try {
    const module = (await import(/* @vite-ignore */ url)) as OrtModule;
    return { module, wasm: model.ortWasm };
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** The export the document holds, or null for a page served by `mosaic view` or opened by hand. */
export async function readExport(doc: Pick<Document, "getElementById">): Promise<Exported | null> {
  const element = doc.getElementById(EXPORT_ID);
  return element === null ? null : parseExport(element.textContent ?? "");
}
