/**
 * Run tool cases on one mosaic in the kit and print the answers (Specification 0.1, sections 8.1,
 * 8.2 and 11: "tool cases with expected answers, on the Chinook mosaic"; plan M3.4).
 *
 *     bun kit/scripts/run-cases.ts FILE CASES.json [--model DIR]
 *
 * `CASES.json` maps each case name to `{"tool": ..., "arguments": {...}}`, at its top level or
 * under `cases` as in `conformance/tools/expected-answers.json` (other fields, such as an expected
 * answer, are ignored). The file is opened as any reader opens it (section 3.8); with
 * `--model`, the model files of section 6 in DIR embed `find`'s queries for the vector tier. Prints
 * one JSON object mapping each case name, in the file's order, to the kit's answer.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MODEL, loadEmbedder, openFile, type OpenOptions, type SealedFile } from "../src/index.js";

type Tool = "find" | "get" | "neighbors" | "table" | "cite";
const TOOLS: readonly Tool[] = ["find", "get", "neighbors", "table", "cite"];

interface Case {
  readonly tool: string;
  readonly arguments: unknown;
}

const args = process.argv.slice(2);
const at = args.indexOf("--model");
const modelDir = at >= 0 ? args[at + 1] : undefined;
const [file, casesFile] = args.filter((_, i) => i !== at && i !== at + 1);
if (!file || !casesFile || (at >= 0 && !modelDir)) {
  console.error("usage: bun kit/scripts/run-cases.ts FILE CASES.json [--model DIR]");
  process.exit(2);
}

const read = JSON.parse(readFileSync(casesFile, "utf8")) as { cases?: Record<string, Case> } & Record<string, Case>;
const cases: Record<string, Case> = read.cases ?? read;
const options: { embedder?: OpenOptions["embedder"] } = {};
if (modelDir) {
  const bytes = (path: string): Uint8Array => new Uint8Array(readFileSync(join(modelDir, path)));
  options.embedder = await loadEmbedder({ model: bytes(MODEL.modelFile.path), tokenizer: bytes(MODEL.tokenizer.path) });
}
const sealed: SealedFile = await openFile(new Uint8Array(readFileSync(file)), file, options);
try {
  const answers: Record<string, unknown> = {};
  for (const [name, c] of Object.entries(cases)) {
    if (!TOOLS.includes(c.tool as Tool)) throw new Error(`case ${name}: unknown tool ${JSON.stringify(c.tool)}`);
    answers[name] = await sealed[c.tool as Tool](c.arguments);
  }
  process.stdout.write(`${JSON.stringify(answers)}\n`);
} finally {
  sealed.close();
}
