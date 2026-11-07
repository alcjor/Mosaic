// The viewer keeps where it is in the address after `#`, so links between node pages work
// without a server (M2.9: a link opens the other node).
import { describe, expect, it } from "vitest";
import { parseRoute, routeHash } from "../src/lib/route.js";

describe("routes", () => {
  it("an empty hash is no query and no node", () => {
    expect(parseRoute("")).toEqual({ query: "", node: null });
    expect(parseRoute("#")).toEqual({ query: "", node: null });
    expect(routeHash({ query: "", node: null })).toBe("#");
  });

  it("any query and node id survive the round trip", () => {
    for (const node of ["Item:a", "Step:FOP-PWR-001/2", "A:b&c=d#e f", "Item:～", "Item:😀", "T:%20+"]) {
      for (const query of ["", "inlet temperature", "a&b=c", "\"quoted\" OR *"]) {
        const route = { query, node };
        expect(parseRoute(routeHash(route))).toEqual(route);
      }
    }
    expect(parseRoute(routeHash({ query: "x", node: null }))).toEqual({ query: "x", node: null });
  });
});
