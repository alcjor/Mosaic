"""The embedding model, the text it embeds and the vectors a mosaic stores (Spec 0.1, 6, 3.7).

Format 0.1 defines one model (section 6): a mosaic's vectors are made by the mosaic builder,
natively, with this exact model file, pinned by its SHA-256; kits only embed queries.

- :data:`MODEL`: the model, its revision and its two files with their hashes;
  :func:`check_file` refuses a file with another hash, naming the file and both hashes.
- :func:`node_text`, :func:`first_snippet` and :func:`query_text`: the text that is embedded.
- :func:`pool`: the first token's output divided by its Euclidean norm.
- :func:`to_bits`: the 48 stored bytes, bit i set when dimension i is greater than 0, most
  significant bit of byte 0 first (section 3.7).

The builder reads the model files from disk and never fetches them (it uses no network).
"""

import hashlib
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PinnedFile:
    """One file of the model, by its path in the model's repository and its SHA-256."""

    path: str
    sha256: str


@dataclass(frozen=True)
class Model:
    """The embedding model of section 6."""

    name: str
    repository: str
    revision: str
    licence: str
    files: tuple[PinnedFile, ...]

    @property
    def model_file(self) -> PinnedFile:
        """The ONNX file whose hash ``embed_model`` names (section 3.7)."""
        return self.files[0]

    @property
    def tokenizer(self) -> PinnedFile:
        return self.files[1]


MODEL = Model(
    name="snowflake-arctic-embed-xs",
    repository="Snowflake/snowflake-arctic-embed-xs",
    revision="d8c86521100d3556476a063fc2342036d45c106f",
    licence="Apache-2.0",
    files=(
        PinnedFile(
            "onnx/model_quantized.onnx",
            "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1",
        ),
        PinnedFile(
            "tokenizer.json",
            "91f1def9b9391fdabe028cd3f3fcc4efd34e5d1f08c3bf2de513ebb5911a1854",
        ),
    ),
)
"""Section 6: model, model file and tokenizer."""

EMBED_MODEL = f"{MODEL.name}@{MODEL.model_file.sha256}"
"""The header's ``embed_model`` of a mosaic with vectors (sections 3.7 and 6)."""

MAX_TOKENS = 256
"""Section 6: input is truncated at 256 tokens."""

DIMENSIONS = 384
"""Dimensions of the model's output; 48 bytes of bits (section 3.7)."""

SNIPPET_CHARS = 800
"""Section 6: the snippet in the node text is cut to its first 800 characters."""

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
"""Section 6: the text before a query."""


class ModelFileError(ValueError):
    """A model file that is missing or is not the pinned file (section 6)."""


def check_file(path: Path, pinned: PinnedFile) -> Path:
    """``path`` if its SHA-256 is the pinned one; otherwise :class:`ModelFileError`."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
    except OSError as e:
        raise ModelFileError(f"{path}: model file {pinned.path} cannot be read: {e}") from None
    actual = digest.hexdigest()
    if actual != pinned.sha256:
        raise ModelFileError(
            f"{path}: model file {pinned.path} has SHA-256 {actual}, not the pinned "
            f"{pinned.sha256} (section 6)"
        )
    return path


def node_text(
    type_: str, key: str, label: str | None, summary: str | None, snippet: str | None
) -> str:
    """``<type> <key>: <label>. <summary> <snippet>`` (section 6).

    An absent summary or snippet is the empty string, and the snippet is cut to its first 800
    characters (code points). Nothing else is changed: no trimming, no joining of spaces.
    """
    cut = "" if snippet is None else snippet[:SNIPPET_CHARS]
    return f"{type_} {key}: {label or ''}. {summary or ''} {cut}"


def first_snippet(snippets: Iterable[tuple[int, str]]) -> str | None:
    """The snippet of a node's node text: the first of its own snippets in ``evid`` order.

    ``snippets`` are ``(evid, text)`` of the node's own evidence rows that keep a snippet (edge
    evidence does not count); ``None`` when there is none. Section 6 says "the snippet"; the
    maintainer chose the first one (reading A, answer on #105).
    """
    first = min(snippets, default=None, key=lambda row: row[0])
    return None if first is None else first[1]


def query_text(query: str) -> str:
    """The text embedded for a query: the prefix of section 6, then the query."""
    return QUERY_PREFIX + query


def pool(output: Sequence[Sequence[float]]) -> list[float]:
    """The first token's output divided by its Euclidean norm (section 6)."""
    if not output:
        raise ValueError("the model's output holds no token")
    first = [float(x) for x in output[0]]
    if len(first) != DIMENSIONS:
        raise ValueError(f"the model's output has {len(first)} dimensions, not {DIMENSIONS}")
    norm = math.sqrt(math.fsum(x * x for x in first))
    if not norm > 0 or not math.isfinite(norm):
        raise ValueError(f"the first token's output has norm {norm}; it cannot be normalised")
    return [x / norm for x in first]


def to_bits(vector: Sequence[float]) -> bytes:
    """48 bytes: bit i is 1 when dimension i is greater than 0, most significant bit first."""
    if len(vector) != DIMENSIONS:
        raise ValueError(f"a vector has {DIMENSIONS} dimensions, not {len(vector)}")
    out = bytearray(DIMENSIONS // 8)
    for i, x in enumerate(vector):
        if x > 0:
            out[i // 8] |= 0x80 >> (i % 8)
    return bytes(out)
