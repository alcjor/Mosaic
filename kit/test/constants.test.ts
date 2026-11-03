import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { APPLICATION_ID, CUT_MARKER, FORMAT_VERSION, TEXT_LIMITS, TOOLS, USER_VERSION, cut } from "../src/index.js";

const spec = (name: string): string =>
  readFileSync(fileURLToPath(new URL(`../../spec/${name}`, import.meta.url)), "utf8");

describe("kit constants agree with the normative files", () => {
  it("matches application_id and user_version in format.sql", () => {
    const sql = spec("format.sql");
    expect(sql).toContain(`PRAGMA application_id = ${APPLICATION_ID};`);
    expect(sql).toContain(`PRAGMA user_version = ${USER_VERSION};`);
    expect(sql).toContain(`CHECK (format_version = '${FORMAT_VERSION}')`);
  });

  it("names the same tools as answers.schema.json", () => {
    const schema = JSON.parse(spec("answers.schema.json")) as {
      $defs: { error: { properties: { tool: { enum: string[] } } } };
    };
    expect([...TOOLS].sort()).toEqual([...schema.$defs.error.properties.tool.enum].sort());
  });
});

describe("cut", () => {
  it("leaves short text alone", () => {
    expect(cut("Inlet", TEXT_LIMITS.label)).toBe("Inlet");
  });

  it("cuts by characters, not UTF-16 units, and marks the cut", () => {
    const long = "°".repeat(TEXT_LIMITS.label + 5);
    const out = cut(long, TEXT_LIMITS.label);
    expect(Array.from(out)).toHaveLength(TEXT_LIMITS.label + 1);
    expect(out.endsWith(CUT_MARKER)).toBe(true);
  });
});
