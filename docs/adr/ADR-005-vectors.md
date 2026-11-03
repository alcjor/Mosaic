# ADR-005: Vectors

**Status:** Accepted, 2026-10-27 · **Deciders:** the maintainer

**Decision: a mosaic's identity hash covers its knowledge, not its vectors; vectors are a derived layer with their own hash and the model that made them. v0 supports exactly one small embedding model, so the full and single-model kits are the same; the bare kit has none.**

## Context

Part 1 decided that mosaics ship precomputed vectors by default, that the full mosaic kit bundles every supported embedding model, that a single-model kit bundles one, and that a bare kit has none and ignores vectors. Two questions remain:

- **Determinism:** the same pieces and pattern must give the same mosaic, but an embedding model can give slightly different numbers on different machines (thread counts, processor instructions, library versions).
- **Kit size:** every bundled model adds tens of megabytes and an inference runtime, which must also run in WebAssembly.

## Part 1: determinism

| Option | How it works | Verdict |
| --- | --- | --- |
| A: Pin everything | Fixed model file, CPU only, one thread, pinned runtime version | Helps, but cannot be guaranteed across platforms |
| B: Binary vectors | Keep only the sign of each value; tiny float differences rarely flip a sign | Shrinks vectors 32 times, but a rare flip still changes the bytes |
| C: Separate layer | The mosaic's identity hash covers nodes, edges, names, evidence and text; vectors carry their own hash and model id | Chosen, with A and B |

So "the same pieces and pattern give the same mosaic" holds for the knowledge, as an identical knowledge hash. Vectors are built with A and stored as in B; a rebuild on another machine may differ in a few bits, which does not change answers and does not change the mosaic's identity. The quality check compares vector layers by agreement (for example 99.9 % of bits equal), not by bytes.

## Part 2: kit tiers

| Tier | Contains | Searches by | Use |
| --- | --- | --- | --- |
| Bare | The reader and tools only | Names, aliases, full-text | Browsers and tiny devices; mosaics without vectors |
| Single-model | Bare plus one embedding model and a portable inference runtime | Names, full-text and meaning | The default for agents |
| Full | Bare plus every supported model | Same, for any mosaic | Hosts that open mosaics from many builders |

v0 supports one embedding model, chosen by the spikes among small open models with a permissive licence and a WebAssembly-capable runtime. Full and single-model are therefore the same kit in v0; a second model is added only when a real need appears. A kit that opens a mosaic built with an unsupported model warns and falls back to names and full-text.

## Consequences

- Easier: reproducibility holds where it matters, and is testable through the knowledge hash.
- Easier: one model in v0 keeps the kit small and the benchmark simple.
- Harder: two hashes per mosaic (knowledge and vectors) to explain and store.
- To revisit: more models, when users bring mosaics built elsewhere; a vector index, if scanning gets slow (ADR-001).

## Amendment, 27 October 2026: the v0 model

**Decision: v0 ships `Snowflake/snowflake-arctic-embed-xs`, official quantized ONNX file (23 MB, Apache-2.0). The mosaic records the model by name and file hash; the kit scores a full-precision query against the stored 48-byte bits.** The exact parameters (file and tokenizer hashes, revision, pooling, node and query text, bit packing) are normative in Part 5, section 6.

Why (spikes S5 and S6, Part 4): it is the only file under the 60 MB single-model budget that keeps its quality as bits; on MTEB retrieval it scores 50.15 against 51.68 for bge-small-en-v1.5, a model whose only file is 133 MB; on the PX4 questions it puts the answer in the top 10 for 32 % (50 % within one hop) against 18 % (39 %) for full-text alone. Different files of the same model change 2.6–8.7 % of bits, hence the file hash.

**Rule: the mosaic builder always computes vectors natively; kits embed only queries.** Spike S5 found that the browser runtime gives slightly different bits (0.87 %) with no effect on search, and is far too slow to embed a whole mosaic (2,000 texts in 187 s). The vector hash is therefore only ever computed from the builder's output. Kit size budgets (ADR-007) are compressed download sizes with every dependency packed: 21 MB for the browser and 51 MB for native Python, both under 60 MB.

- Harder: embedding the 18,000-node PX4 mosaic took about 8–10 minutes on 4 CPU threads; this led ADR-007 to relax the build budget with vectors from 5 to 15 minutes.
- To revisit: snowflake-arctic-embed-s (MTEB 51.98) if an official small file exists; the native kit's margin: 51 MB of its 60 MB compressed budget, mostly ONNX Runtime; a smaller runtime build would widen it.
