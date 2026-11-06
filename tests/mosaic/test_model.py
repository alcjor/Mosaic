"""Fetching and running the embedding model of section 6.

Section 6: the model file and tokenizer are pinned by SHA-256 and "truncate at 256 tokens";
the embedding is "the first token's output, divided by its Euclidean norm". Plan M2.6: "The
model file and tokenizer of §6 are fetched from an origin an agent environment reaches and
checked by their SHA-256; a file with another hash is refused, naming the file and both hashes."

The fast tests use an invented origin and an invented tokenizer; the ``slow`` tests fetch the
real model (once, into ``.cache/model/``) and run it.
"""

import hashlib
import importlib.util
import math
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
from mosaic_build.mosaic import vectors as v
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from tests.conftest import REPO


def _load() -> ModuleType:
    path = REPO / "scripts" / "fetch_model.py"
    spec = importlib.util.spec_from_file_location("fetch_model", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_model"] = module
    spec.loader.exec_module(module)
    return module


fm = _load()


# --- fetching ------------------------------------------------------------------------------


def _origin(tmp_path: Path, contents: dict[str, bytes]) -> str:
    root = tmp_path / "origin"
    for name, data in contents.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    return root.as_uri()


def _pinned(monkeypatch: pytest.MonkeyPatch, contents: dict[str, bytes]) -> None:
    files = tuple(v.PinnedFile(n, hashlib.sha256(d).hexdigest()) for n, d in contents.items())
    monkeypatch.setattr(fm, "MODEL", replace(v.MODEL, files=files))


def test_fetch_downloads_every_pinned_file_and_checks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {"onnx/model.onnx": b"weights", "tokenizer.json": b"{}"}
    _pinned(monkeypatch, contents)
    dest = fm.fetch(tmp_path / "model", _origin(tmp_path, contents))
    for name, data in contents.items():
        assert (dest / name).read_bytes() == data
    assert not list(dest.rglob("*.part"))


def test_fetch_refuses_a_file_with_another_hash_naming_it_and_both_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pinned(monkeypatch, {"onnx/model.onnx": b"the pinned weights"})
    origin = _origin(tmp_path, {"onnx/model.onnx": b"other weights"})
    with pytest.raises(v.ModelFileError) as caught:
        fm.fetch(tmp_path / "model", origin)
    message = str(caught.value)
    assert "onnx/model.onnx" in message and origin in message
    assert hashlib.sha256(b"the pinned weights").hexdigest() in message
    assert hashlib.sha256(b"other weights").hexdigest() in message
    assert not (tmp_path / "model" / "onnx" / "model.onnx").exists()
    assert not list((tmp_path / "model").rglob("*.part"))


def test_fetch_keeps_a_file_that_already_has_its_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {"tokenizer.json": b"{}"}
    _pinned(monkeypatch, contents)
    dest = tmp_path / "model"
    (dest).mkdir()
    (dest / "tokenizer.json").write_bytes(b"{}")
    fm.fetch(dest, (tmp_path / "nowhere").as_uri())  # an origin with nothing: not used


def test_fetch_replaces_a_file_with_another_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {"tokenizer.json": b"{}"}
    _pinned(monkeypatch, contents)
    dest = tmp_path / "model"
    dest.mkdir()
    (dest / "tokenizer.json").write_bytes(b"stale")
    fm.fetch(dest, _origin(tmp_path, contents))
    assert (dest / "tokenizer.json").read_bytes() == b"{}"


def test_the_default_origin_is_the_pinned_revision_of_the_model() -> None:
    assert fm.ORIGIN == (
        "https://huggingface.co/Snowflake/snowflake-arctic-embed-xs/resolve/"
        "d8c86521100d3556476a063fc2342036d45c106f"
    )


def test_main_reports_a_refused_file_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pinned(monkeypatch, {"tokenizer.json": b"{}"})
    origin = _origin(tmp_path, {"tokenizer.json": b"[]"})
    assert fm.main(["--dest", str(tmp_path / "m"), "--origin", origin]) == 1
    assert "tokenizer.json" in capsys.readouterr().err


# --- truncation at 256 tokens --------------------------------------------------------------


def _word_tokenizer(path: Path) -> Path:
    """An invented tokenizer: one token per word, [CLS] and [SEP] around them, no limit."""
    words = {"[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3, "w": 4}
    tok = Tokenizer(models.WordLevel(words, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 2), ("[SEP]", 3)]
    )
    tok.enable_truncation(512)
    tok.save(str(path))
    return path


def test_input_is_truncated_at_256_tokens_with_its_special_tokens(tmp_path: Path) -> None:
    tok = v.load_tokenizer(_word_tokenizer(tmp_path / "tokenizer.json"))
    ids = tok.encode("w " * 1000).ids
    assert len(ids) == v.MAX_TOKENS
    assert ids[0] == 2 and ids[-1] == 3


def test_shorter_input_is_not_padded(tmp_path: Path) -> None:
    tok = v.load_tokenizer(_word_tokenizer(tmp_path / "tokenizer.json"))
    assert tok.encode("w w w").ids == [2, 4, 4, 4, 3]


def test_the_embedder_refuses_model_files_that_are_not_pinned(tmp_path: Path) -> None:
    (tmp_path / "onnx").mkdir()
    (tmp_path / "onnx" / "model_quantized.onnx").write_bytes(b"not the model")
    with pytest.raises(v.ModelFileError, match=r"onnx/model_quantized\.onnx"):
        v.Embedder(tmp_path)


# --- the real model (slow) -----------------------------------------------------------------


@pytest.fixture(scope="module")
def embedder() -> v.Embedder:
    return v.Embedder(fm.fetch())


@pytest.mark.slow
def test_the_real_tokenizer_truncates_at_256_tokens(embedder: v.Embedder) -> None:
    ids = embedder.tokenizer.encode("word " * 2000).ids
    assert len(ids) == v.MAX_TOKENS
    assert embedder.tokenizer.id_to_token(ids[0]) == "[CLS]"
    assert embedder.tokenizer.id_to_token(ids[-1]) == "[SEP]"


@pytest.mark.slow
def test_embeddings_are_unit_vectors_of_384_dimensions(embedder: v.Embedder) -> None:
    vector = embedder.embed(v.node_text("Item", "a", "Item A", "The first item", "a,1,x"))
    assert len(vector) == v.DIMENSIONS
    assert math.isclose(math.fsum(x * x for x in vector), 1.0, rel_tol=1e-9)


@pytest.mark.slow
def test_the_same_text_gives_the_same_bits(embedder: v.Embedder) -> None:
    text = v.node_text("Item", "a", "Item A", None, "a,1,x")
    assert embedder.bits(text) == embedder.bits(text)
    assert len(embedder.bits(text)) == 48


@pytest.mark.slow
def test_text_past_256_tokens_does_not_change_the_embedding(embedder: v.Embedder) -> None:
    head = "word " * 300
    assert embedder.embed(head) == embedder.embed(head + "something else entirely")


@pytest.mark.slow
def test_a_query_is_embedded_with_the_prefix_and_ranks_its_match_first(
    embedder: v.Embedder,
) -> None:
    query = embedder.query("a small fish living in rivers")
    assert query == embedder.embed(v.query_text("a small fish living in rivers"))
    texts = {
        "fish": v.node_text("Animal", "minnow", "Minnow", "A small freshwater fish", None),
        "tax": v.node_text("Rule", "vat", "Value added tax", "A tax on goods and services", None),
    }
    scores = {
        name: sum(q if b else -q for q, b in zip(query, _signs(embedder.bits(t)), strict=True))
        for name, t in texts.items()
    }
    assert scores["fish"] > scores["tax"]


def _signs(bits: bytes) -> list[bool]:
    return [bool(bits[i // 8] & (0x80 >> (i % 8))) for i in range(v.DIMENSIONS)]
