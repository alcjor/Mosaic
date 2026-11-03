# ADR-007: Budgets

**Status:** Accepted, 2026-10-27 · **Deciders:** the maintainer

**Decision: fix provisional budgets now, check them in CI on test data at two sizes, and let the benchmark move them.** Every number in the budget table is a starting point, not a measurement; measurements follow below it.

## Context

Part 1 promises mosaics that are small, fast enough for an interactive agent, and usable by a 7 to 9B model on a laptop, but gives no numbers. Without budgets, size and speed drift one feature at a time, and the tiny-mosaic threshold has no basis. Budgets are set for two reference sizes: **standard**, 10,000 nodes (a subsystem or a small plant), and **large**, 100,000 nodes, the v0 maximum.

## Budgets and measurements

Measured on 27 October 2026 on the PX4 corpus (17,905 nodes) and a six-fold copy (107,430 nodes), on one Linux container, with headless Chromium for the browser (Part 4).

| Area | Budget | Notes | Measured | Verdict |
| --- | --- | --- | --- | --- |
| Nodes per mosaic | Up to 100,000 in v0 | Bigger systems are split into several mosaics (principle 2) | 107,430 nodes, 117 MB with snippets and vectors, all tools fast | Met |
| Size without text or vectors | About 1 KB per node on average | Node, aliases, evidence, link counts and indexes | 650 B per node | Met |
| Vectors | 48 bytes per node | 384 dimensions, binary (ADR-005) | 48 B per node, 5 % of the file | Met |
| Size with snippets | Standard mosaic under 20 MB | Snippets dominate; text tier decided per source | 19.5 MB at 17,905 nodes, so a 20 MB standard mosaic holds about 18,000 nodes | Met, little margin |
| Card | Under 1,500 tokens | Generated (ADR-006) | Not measured; the card generator does not exist yet | Open |
| Tool answer | Under 500 tokens by default; lists cut at 20 items with a count | Configurable per host | Not measured; one node id costs 11 tokens on average for Qwen2.5 and 16 for SmolLM2, so 20 ids are about 220–320 tokens | Open, ids fit |
| Tool latency, native | Under 100 ms at the 95th percentile on a large mosaic for `find`, `get`, `neighbors`, `cite` and a page of `table`; `path` up to 4 hops under 300 ms | Excludes the model's own time | p95 at 107k: `find` 5.9 ms, `get`, `neighbors`, `cite` under 0.05 ms, `table` page 7 ms, `path` (4 hops) 0.5 ms | Met |
| Tool latency, browser | Within 3 times native | WebAssembly | p95 at 107k: `find` 6.4 ms, others under 10 ms | Met |
| Open time | Under 1 s native, under 3 s in a browser, standard mosaic | Includes hash checks | Native: 0.15 s at 18k cold, 0.97 s at 107k cold. Browser: 0.3 s and 2.6 s | Met; 107k close to both limits |
| Build time | Standard mosaic under 30 s without vectors, under 15 min with vectors on a laptop CPU (relaxed from 5 min on 27 October 2026: embedding dominates and happens once per build) | From tesserae; tessera builders not included | Without vectors about 2 s (spike loader, a lower bound). With vectors about 8–10 min at 18k nodes on 4 CPU threads | Met after relaxing to 15 min |
| Bare kit | Under 3 MB compressed download, dependencies included | Reader, tools, SQLite | SQLite WebAssembly 619 KB compressed; kit code not written | Open, SQLite well within |
| Single-model kit | Under 60 MB compressed download, dependencies included (runtime, model, tokenizer) | One small embedding model and its runtime | Browser 21 MB (40 MB on disk), native Python 51 MB (134 MB installed; ONNX Runtime is the largest part) | Met |
| Tiny-mosaic threshold | Whole graph as compact text when it fits in a quarter of the model's context | 8,000 tokens for a 32,000-token model; the rest stays free for the conversation | Not measured | Open |

## Options considered

| Option | Verdict |
| --- | --- |
| A: Provisional numbers now, checked in CI, moved by the benchmark | Chosen |
| B: No numbers until the benchmark exists | Rejected: the first builds would set the budgets by accident |
| C: Strict numbers that fail builds | Rejected for v0: too early to know the right values; warnings first |

## Consequences

- Easier: every change shows its cost in size and speed, and regressions are visible in CI.
- Easier: the tiny-mosaic threshold follows each model's context instead of one fixed number.
- Harder: test data must exist at both sizes before the numbers mean anything.
- To revisit: every budget after the first benchmark run; nodes beyond 100,000 if real systems need it.
