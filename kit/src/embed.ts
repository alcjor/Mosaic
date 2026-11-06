/**
 * The query embedding of the vector tier (Specification 0.1, section 6), run in the page.
 *
 * The kit supports the one model of format 0.1. {@link loadEmbedder} takes the bytes of its two
 * files, checks each by its pinned SHA-256 (a file with another hash is refused, naming the file
 * and both hashes), and runs the model with ONNX Runtime's WebAssembly build, on the CPU, one
 * thread (its WebAssembly-only build, `onnxruntime-web/wasm`, without WebGPU). A query is embedded as section 6 says: the query text (the prefix, then the query),
 * tokenized and truncated at 256 tokens, the model's output for the first token divided by its
 * Euclidean norm. The vector stays at full precision: scoring never turns it into bits.
 *
 * ONNX Runtime is loaded only by {@link loadEmbedder}, so the bare kit (no vector tier) does not
 * carry it.
 */
import { Sha256 } from "./sha256.js";
import { WordPiece } from "./wordpiece.js";

/** Section 6: the model, its file and its tokenizer, pinned by SHA-256. */
export const MODEL = {
  name: "snowflake-arctic-embed-xs",
  repository: "Snowflake/snowflake-arctic-embed-xs",
  revision: "d8c86521100d3556476a063fc2342036d45c106f",
  modelFile: { path: "onnx/model_quantized.onnx", sha256: "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1" },
  tokenizer: { path: "tokenizer.json", sha256: "91f1def9b9391fdabe028cd3f3fcc4efd34e5d1f08c3bf2de513ebb5911a1854" },
} as const;

/** The header's `embed_model` of a mosaic whose vectors this kit can search (sections 3.7, 6). */
export const EMBED_MODEL = `${MODEL.name}@${MODEL.modelFile.sha256}`;

/** Section 6: input is truncated at 256 tokens, special tokens counted. */
export const MAX_TOKENS = 256;

/** Dimensions of an embedding; 48 bytes of bits (section 3.7). */
export const DIMENSIONS = 384;

/** Section 6: the text before a query. */
export const QUERY_PREFIX = "Represent this sentence for searching relevant passages: ";

/** The text embedded for `query` (section 6). */
export function queryText(query: string): string {
  return QUERY_PREFIX + query;
}

/** What embeds queries for the vector tier: the model it runs, and the normalised vector. */
export interface QueryEmbedder {
  /** The `embed_model` value of the mosaics whose vectors it can search. */
  readonly model: string;
  /** The normalised embedding of `query`'s query text: {@link DIMENSIONS} finite numbers. */
  embedQuery(query: string): Promise<Float32Array>;
}

/** A model file that is not the pinned one (section 6). */
export class ModelFileError extends Error {
  override readonly name = "ModelFileError";
}

function check(bytes: Uint8Array, pinned: { path: string; sha256: string }): void {
  const actual = new Sha256().update(bytes).hex();
  if (actual !== pinned.sha256) {
    throw new ModelFileError(
      `model file ${pinned.path} has SHA-256 ${actual}, not the pinned ${pinned.sha256} (section 6)`,
    );
  }
}

/** The first token's output divided by its Euclidean norm (section 6). */
export function pool(hidden: Float32Array, dimensions: number = DIMENSIONS): Float32Array {
  if (hidden.length < dimensions) throw new Error("the model's output holds no token");
  const first = hidden.subarray(0, dimensions);
  let norm = 0;
  for (const x of first) norm = Math.hypot(norm, x);
  if (!(norm > 0) || !Number.isFinite(norm)) throw new Error(`the first token's output has norm ${norm}`);
  return Float32Array.from(first, (x) => x / norm);
}

export interface ModelFiles {
  /** The bytes of `onnx/model_quantized.onnx`. */
  readonly model: Uint8Array;
  /** The bytes of `tokenizer.json`. */
  readonly tokenizer: Uint8Array;
}

/** The model of section 6 from its files, which must be the pinned ones. */
export async function loadEmbedder(files: ModelFiles): Promise<QueryEmbedder> {
  check(files.model, MODEL.modelFile);
  check(files.tokenizer, MODEL.tokenizer);
  const tokenizer = new WordPiece(new TextDecoder("utf-8", { fatal: true }).decode(files.tokenizer));
  const ort = await import("onnxruntime-web/wasm");
  ort.env.wasm.numThreads = 1;
  ort.env.logLevel = "error";
  const session = await ort.InferenceSession.create(files.model.slice(), {
    executionProviders: ["wasm"],
    graphOptimizationLevel: "all",
  });
  const tensor = (values: number[]) =>
    new ort.Tensor("int64", BigInt64Array.from(values, (v) => BigInt(v)), [1, values.length]);
  // One query at a time: a run is not shared between calls.
  let queue: Promise<unknown> = Promise.resolve();
  return {
    model: EMBED_MODEL,
    embedQuery(query: string): Promise<Float32Array> {
      const run = queue.then(async () => {
        const ids = tokenizer.encode(queryText(query), MAX_TOKENS);
        const output = await session.run({
          input_ids: tensor(ids),
          attention_mask: tensor(ids.map(() => 1)),
          token_type_ids: tensor(ids.map(() => 0)),
        });
        const hidden = output["last_hidden_state"];
        if (!hidden || !(hidden.data instanceof Float32Array)) throw new Error("the model gave no last_hidden_state");
        return pool(hidden.data);
      });
      queue = run.catch(() => undefined);
      return run;
    },
  };
}
