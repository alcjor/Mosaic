/**
 * The kit's bounds on query time and result size (Specification 0.1, section 3.8 step 4 and
 * section 10). Every value in a file is untrusted, so no tool call may run or grow without end:
 *
 * - a list holds at most {@link RESULT_LIMIT} items, with the total count (section 8.2);
 * - a query is at most {@link QUERY_LIMIT} characters;
 * - a tool call stops after {@link TIME_LIMIT_MS} milliseconds of SQLite work (or the time
 *   given when the file is opened), with a `limit_exceeded` error naming the bound.
 */
import type { Database, Sqlite3Static } from "@sqlite.org/sqlite-wasm";
import { ToolError } from "./answers.js";

/** Most items in a list (section 8.2): a larger `limit` still gives at most this many. */
export const RESULT_LIMIT = 20;

/** Longest query, in characters, a tool takes. */
export const QUERY_LIMIT = 1000;

/** Default time bound of one tool call, in milliseconds. */
export const TIME_LIMIT_MS = 1000;

/** SQLite virtual machine steps between two looks at the clock. */
const STEPS_PER_CHECK = 1000;

/** A clock on one database: tool calls run under it, and SQLite stops them at the deadline. */
export class Deadline {
  private until = Number.POSITIVE_INFINITY;
  private stopped = false;

  constructor(
    s: Sqlite3Static,
    db: Database,
    /** The bound, in milliseconds. */
    readonly limitMs: number,
  ) {
    s.capi.sqlite3_progress_handler(
      db,
      STEPS_PER_CHECK,
      () => {
        if (performance.now() <= this.until) return 0;
        this.stopped = true;
        return 1;
      },
      0,
    );
  }

  /** Run `work` under the bound; past it, SQLite stops and a `limit_exceeded` error says so. */
  run<T>(tool: string, work: () => T): T {
    this.until = performance.now() + this.limitMs;
    this.stopped = false;
    try {
      return work();
    } catch (e) {
      if (this.stopped) {
        throw new ToolError(
          "limit_exceeded",
          `${tool} stopped: it ran past the kit's time bound of ${this.limitMs} ms (section 3.8 step 4)`,
        );
      }
      throw e;
    } finally {
      this.until = Number.POSITIVE_INFINITY;
    }
  }
}
