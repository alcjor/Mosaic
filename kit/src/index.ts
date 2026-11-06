/**
 * The mosaic kit (Specification 0.1, section 8).
 *
 * Opens one mosaic read-only and offers six read-only tools; `find`, `get` and `cite` are here,
 * `neighbors` and `table` arrive in M2, `path` later. This module gathers what the kit exports.
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
  type CiteAnswer,
  type CiteEvidence,
  type ErrorAnswer,
  type ErrorCode,
  type FindAnswer,
  type FindResult,
  type GetAnswer,
  type GetData,
  type Match,
} from "./answers.js";

export { QUERY_LIMIT, RESULT_LIMIT, TIME_LIMIT_MS } from "./bounds.js";

export { textQuery, type FindArgs } from "./find.js";

export { type GetArgs } from "./get.js";

export { type CiteArgs } from "./cite.js";

export { ID_LIMIT } from "./lookup.js";
