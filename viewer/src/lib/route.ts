/**
 * Where the viewer is, kept in the page's address after `#`, so the browser's back button,
 * links and bookmarks work without a server: `#q=<query>&node=<id>`, both optional. A link to
 * a node keeps the search beside it.
 */

export interface Route {
  /** The search box's query; empty when there is none. */
  readonly query: string;
  /** The id of the node whose page is open, or null. */
  readonly node: string | null;
}

/** The route a location hash names; anything it does not name is empty. */
export function parseRoute(hash: string): Route {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  return { query: params.get("q") ?? "", node: params.get("node") };
}

/** The location hash of `route`, as {@link parseRoute} reads it. */
export function routeHash(route: Route): string {
  const params = new URLSearchParams();
  if (route.query !== "") params.set("q", route.query);
  if (route.node !== null) params.set("node", route.node);
  const text = params.toString();
  return text === "" ? "#" : `#${text}`;
}
