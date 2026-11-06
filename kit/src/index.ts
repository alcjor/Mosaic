/**
 * The mosaic kit (Specification 0.1, section 8).
 *
 * Opens one mosaic read-only and offers six read-only tools. Implementation
 * arrives in M2; this module gathers what the kit exports.
 */

export * from "./constants.js";

export {
  FileRefusedError,
  IMPLEMENTED_VERSIONS,
  REFUSAL_RULES,
  openFile,
  type Header,
  type RefusalRule,
  type SealedFile,
} from "./open.js";

export { PARTS, VECTOR_BYTES, encodeKnowledge, knowledgeHash, vectorHash } from "./hashes.js";
