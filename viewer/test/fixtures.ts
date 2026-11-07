// The files the viewer tests open: conformance cases, invented data (conformance/reading/).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function reading(name: string): Uint8Array {
  const path = fileURLToPath(new URL(`../../conformance/reading/${name}`, import.meta.url));
  return new Uint8Array(readFileSync(path));
}
