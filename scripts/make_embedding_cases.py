"""Write ``conformance/embedding/cases.json``: queries the builder's model embeds (Spec 0.1, 6).

For each invented query, the case records the text the model embeds (the section 6 prefix, then
the query), the token ids the pinned tokenizer gives it (truncated at 256 tokens, special tokens
included), and the signs of the builder's normalised embedding as the 48 bytes of section 3.7,
in hex. A kit embeds the same queries in its own runtime: its tokens must be the same, and its
vector must agree in sign with the builder's on at least 98 % of the 384 dimensions (plan M2.8;
spike S5 measured 0.87 % differing).

    uv run python scripts/fetch_model.py
    uv run python scripts/make_embedding_cases.py [--model DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mosaic_build.mosaic.vectors import EMBED_MODEL, MAX_TOKENS, Embedder, query_text, to_bits

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "conformance" / "embedding" / "cases.json"
MODEL_DIR = (
    REPO / ".cache" / "model" / "snowflake-arctic-embed-xs@d8c86521100d3556476a063fc2342036d45c106f"
)

QUERIES = [
    "",
    "a",
    "inlet temperature",
    "Inlet Temperature",
    "INLET TEMPERATURE SENSOR",
    "which step switches the heater on?",
    "TEMP-3",
    "PARAM_X.Y",
    "café crème brûlée",
    "naïve résumé coöperation",
    "Ångström and Øre",
    "über straße",
    "温度传感器的读数",
    "日本語のテキストと English mixed",
    "온도 센서",
    "Москва и Санкт-Петербург",
    "Αθήνα",
    "مرحبا بالعالم",
    "😀 emoji 🚀 rocket",
    "tab\tseparated\nnew line\r\nand  double  spaces",
    "control\u0001char and ​zero width",
    "quotes \"double\" and 'single' (brackets) [square] {curly}",
    "punctuation!?.,;:-_/\\|@#$%^&*+=~`<>",
    "numbers 1234567890 and 3.14159 and 1e-9",
    "a film about a lonely robot who falls in love in space",
    "documentary on ocean life and coral reefs",
    "supercalifragilisticexpialidocious antidisestablishmentarianism",
    "x" * 150,
    "ID-00042 / rev. B, sheet 3 of 7",
    " leading and trailing spaces ",
    "İstanbul ǅemal ﬁne ﬂow",
    "".join(chr(0xFEE0 + ord(c)) if c != " " else c for c in "fullwidth ABC 123"),
    " ".join(["word"] * 400),
    " ".join(f"token{i}" for i in range(300)),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, default=MODEL_DIR)
    args = parser.parse_args(argv)
    embedder = Embedder(args.model)
    cases = []
    for query in QUERIES:
        text = query_text(query)
        ids = embedder.tokenizer.encode(text).ids
        assert len(ids) <= MAX_TOKENS
        cases.append(
            {"query": query, "text": text, "ids": ids, "bits": to_bits(embedder.query(query)).hex()}
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = {"embed_model": EMBED_MODEL, "max_tokens": MAX_TOKENS, "cases": cases}
    OUT.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
