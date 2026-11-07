/**
 * The mosaic kit (Specification 0.1, section 8).
 *
 * Opens one mosaic read-only and offers six read-only tools; `find`, `get`, `neighbors`, `table`
 * and `cite` are here, `path` arrives later. This module gathers what the kit exports.
 */

export * from "./constants.js";

export {
  FileRefusedError,
  IMPLEMENTED_VERSIONS,
  NODE_TYPE_LIMIT,
  REFUSAL_RULES,
  openFile,
  useSqliteWasm,
  type Header,
  type EdgeType,
  type NodeType,
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
  type NeighborEdge,
  type NeighborsAnswer,
  type TableAnswer,
} from "./answers.js";

export { QUERY_LIMIT, RESULT_LIMIT, TIME_LIMIT_MS } from "./bounds.js";

export { textQuery, type FindArgs } from "./find.js";

export { type GetArgs } from "./get.js";

export { type NeighborsArgs } from "./neighbors.js";

export { type TableArgs, type TableCondition, type TableOrder } from "./table.js";

export { type CiteArgs } from "./cite.js";

export { ID_LIMIT } from "./lookup.js";

export {
  DIMENSIONS,
  EMBED_MODEL,
  MAX_TOKENS,
  MODEL,
  ModelFileError,
  QUERY_PREFIX,
  loadEmbedder,
  pool,
  queryText,
  type ModelFiles,
  type OrtModule,
  type Runtime,
  type QueryEmbedder,
} from "./embed.js";

export { score } from "./vectors.js";

export { TokenizerError, WordPiece, normalise, words } from "./wordpiece.js";
