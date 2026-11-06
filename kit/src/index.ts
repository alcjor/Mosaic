/**
 * The mosaic kit (Specification 0.1, section 8).
 *
 * Opens one mosaic read-only and offers six read-only tools; `find` is here, the others arrive
 * in M2. This module gathers what the kit exports.
 */

export * from "./constants.js";

export {
  FileRefusedError,
  IMPLEMENTED_VERSIONS,
  REFUSAL_RULES,
  openFile,
  type Header,
  type OpenOptions,
  type RefusalRule,
  type SealedFile,
} from "./open.js";

export { PARTS, VECTOR_BYTES, encodeKnowledge, knowledgeHash, vectorHash } from "./hashes.js";

export {
  ToolError,
  type Answer,
  type ErrorAnswer,
  type ErrorCode,
  type FindAnswer,
  type FindResult,
  type Match,
} from "./answers.js";

export { QUERY_LIMIT, RESULT_LIMIT, TIME_LIMIT_MS } from "./bounds.js";

export { textQuery, type FindArgs } from "./find.js";
