/**
 * Scoring of the vector tier (Specification 0.1, section 6): a node's score is the dot product
 * of the full-precision, normalised query vector with the node's stored vector read as +1 for a
 * 1 bit and −1 for a 0 bit (bit i of the 384 is bit `7 - i % 8` of byte `i / 8`, most
 * significant first, section 3.7). The query is never turned into bits.
 */
import { DIMENSIONS } from "./embed.js";

/** The score of the stored `bits` (48 bytes) for `query` (384 numbers). */
export function score(query: Float32Array, bits: Uint8Array): number {
  if (query.length !== DIMENSIONS) throw new Error(`a query vector has ${DIMENSIONS} dimensions, not ${query.length}`);
  if (bits.length !== DIMENSIONS / 8) throw new Error(`a stored vector has ${DIMENSIONS / 8} bytes, not ${bits.length}`);
  let sum = 0;
  for (let i = 0; i < DIMENSIONS; i++) {
    sum += (bits[i >> 3]! & (0x80 >> (i & 7))) !== 0 ? query[i]! : -query[i]!;
  }
  return sum;
}

const encoder = new TextEncoder();

/** Order text by its UTF-8 bytes, as the specification compares text (section 3.6). */
export function compareUtf8(a: string, b: string): number {
  const x = encoder.encode(a);
  const y = encoder.encode(b);
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) if (x[i] !== y[i]) return x[i]! - y[i]!;
  return x.length - y.length;
}
