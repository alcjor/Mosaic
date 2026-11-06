"""Edge cases of the embedding model slice (Specification 0.1, section 6; plan M2.6).

Written from the spec's words: node text, query text, pooling, the 48 stored bytes, the pinned
files and the 256-token truncation. The fast tests need no model; the ``slow`` tests use the
real model fetched into ``.cache/model/``.
"""

import hashlib
import importlib.util
import math
import shutil
import struct
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
from mosaic_build.mosaic import vectors as v

from tests.conftest import REPO

MODEL_REL = "onnx/model_quantized.onnx"
TOKENIZER_REL = "tokenizer.json"


def _load_fetch() -> ModuleType:
    path = REPO / "scripts" / "fetch_model.py"
    spec = importlib.util.spec_from_file_location("fetch_model_edges", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_model_edges"] = module
    spec.loader.exec_module(module)
    return module


fm = _load_fetch()


# --- node text (section 6, "Node text") ----------------


def test_a_snippet_of_exactly_800_characters_is_kept_whole() -> None:
    snippet = "s" * 800
    assert v.node_text("T", "k", "L", None, snippet) == "T k: L.  " + snippet


def test_a_snippet_of_801_characters_loses_only_the_last() -> None:
    snippet = "s" * 800 + "t"
    assert v.node_text("T", "k", "L", None, snippet) == "T k: L.  " + "s" * 800


def test_the_cut_counts_characters_not_utf16_units_or_bytes() -> None:
    snippet = "\U0001f600" * 801  # outside the BMP: 2 UTF-16 units, 4 UTF-8 bytes each
    text = v.node_text("T", "k", "L", None, snippet)
    assert text == "T k: L.  " + "\U0001f600" * 800


def test_the_cut_never_splits_a_character_in_two_bytes_of_utf8() -> None:
    text = v.node_text("T", "k", "L", None, "é" * 900)
    text.encode("utf-8")  # raises if a surrogate or half character was produced
    assert text.endswith("é" * 800) and not text.endswith("é" * 801)


def test_an_empty_snippet_equals_an_absent_one() -> None:
    assert v.node_text("T", "k", "L", "S", "") == v.node_text("T", "k", "L", "S", None)
    assert v.node_text("T", "k", "L", "", "x") == v.node_text("T", "k", "L", None, "x")


def test_only_the_snippet_is_cut_never_the_summary_label_or_key() -> None:
    long = "w" * 5000
    text = v.node_text("T", long, long, long, long)
    assert text == f"T {long}: {long}. {long} " + "w" * 800


def test_nul_and_newlines_survive_in_every_field() -> None:
    text = v.node_text("T", "k\x00", "L\x00\n", "S\x00", "x\x00y\r\n")
    assert text == "T k\x00: L\x00\n. S\x00 x\x00y\r\n"


def test_a_nul_inside_the_first_800_characters_counts_as_a_character() -> None:
    text = v.node_text("T", "k", "L", None, "\x00" * 801)
    assert text == "T k: L.  " + "\x00" * 800


def test_a_key_with_a_colon_is_not_escaped() -> None:
    assert v.node_text("T", "a:b", "L", None, None) == "T a:b: L.  "


def test_node_text_is_deterministic() -> None:
    args = ("Item", "a", "Item A", "sum", "snip")
    assert v.node_text(*args) == v.node_text(*args)


def test_node_text_keeps_decomposed_and_composed_forms_apart() -> None:
    # Text compares by UTF-8 bytes; the text is not normalised before embedding.
    composed = v.node_text("T", "k", "é", None, None)
    decomposed = v.node_text("T", "k", "é", None, None)
    assert composed != decomposed
    assert decomposed == "T k: é.  "


# --- the first snippet (reading A, answer on #105) ----------------


def test_the_first_snippet_is_the_lowest_evid_whatever_the_input_order() -> None:
    assert v.first_snippet([(5, "e"), (1, "a"), (3, "c")]) == "a"
    assert v.first_snippet([(1, "a"), (3, "c"), (5, "e")]) == "a"
    assert v.first_snippet([(3, "c"), (5, "e"), (1, "a")]) == "a"


def test_the_first_snippet_orders_evid_numerically_not_as_text() -> None:
    assert v.first_snippet([(10, "ten"), (9, "nine")]) == "nine"


def test_the_first_snippet_takes_any_iterable_once() -> None:
    def gen() -> Iterator[tuple[int, str]]:
        yield 2, "b"
        yield 1, "a"

    assert v.first_snippet(gen()) == "a"


def test_a_single_snippet_is_the_first() -> None:
    assert v.first_snippet([(7, "only")]) == "only"


# --- query text (section 6, "Query text") ----------------


def test_the_query_text_of_an_empty_query_is_the_prefix_alone() -> None:
    assert v.query_text("") == v.QUERY_PREFIX


def test_the_query_is_not_trimmed_or_changed() -> None:
    q = "  Where?\n\x00 é  "
    assert v.query_text(q) == v.QUERY_PREFIX + q


def test_a_query_that_starts_with_the_prefix_gets_it_again() -> None:
    assert v.query_text(v.QUERY_PREFIX + "x") == v.QUERY_PREFIX + v.QUERY_PREFIX + "x"


# --- pooling (section 6, "Pooling") ----------------


def _first(values: list[float]) -> list[list[float]]:
    return [values, [123.0] * v.DIMENSIONS]


def test_only_the_first_token_is_read_even_when_later_tokens_differ_in_width() -> None:
    first = [0.0] * v.DIMENSIONS
    first[5] = 2.0
    ragged = [first, [1.0, 2.0], []]
    assert v.pool(ragged)[5] == 1.0


def test_pooling_a_single_token_output_works() -> None:
    first = [0.0] * v.DIMENSIONS
    first[0] = -7.0
    out = v.pool([first])
    assert out[0] == -1.0 and sum(out) == -1.0


def test_pooling_keeps_the_signs_and_the_ratios() -> None:
    first = [float((i % 7) - 3) for i in range(v.DIMENSIONS)]
    first[0] = 5.0
    out = v.pool(_first(first))
    norm = math.sqrt(math.fsum(x * x for x in first))
    for a, b in zip(first, out, strict=True):
        assert math.isclose(a / norm, b, rel_tol=1e-12, abs_tol=1e-15)


def test_pooling_scale_does_not_change_the_vector() -> None:
    first = [math.sin(i) for i in range(v.DIMENSIONS)]
    small = v.pool(_first(first))
    big = v.pool(_first([x * 1024.0 for x in first]))
    assert all(
        math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-15) for a, b in zip(small, big, strict=True)
    )


def test_pooling_a_vector_with_huge_values_still_gives_a_unit_vector() -> None:
    # The Euclidean norm of [1e200, 1e200, 0, ...] is finite (1.414e200); squaring overflows.
    first = [0.0] * v.DIMENSIONS
    first[0] = first[1] = 1e200
    out = v.pool(_first(first))
    assert math.isclose(out[0], 1 / math.sqrt(2), rel_tol=1e-12)
    assert math.isclose(math.fsum(x * x for x in out), 1.0, rel_tol=1e-12)


def test_pooling_a_vector_with_tiny_values_still_gives_a_unit_vector() -> None:
    # The norm of [1e-200, 1e-200, 0, ...] is not zero (1.414e-200); squaring underflows to 0.
    first = [0.0] * v.DIMENSIONS
    first[0] = first[1] = 1e-200
    out = v.pool(_first(first))
    assert math.isclose(out[1], 1 / math.sqrt(2), rel_tol=1e-12)


def test_pooling_does_not_change_its_input() -> None:
    first = [1.0] * v.DIMENSIONS
    out = [list(first), [2.0] * v.DIMENSIONS]
    v.pool(out)
    assert out == [[1.0] * v.DIMENSIONS, [2.0] * v.DIMENSIONS]


def test_pooling_twice_gives_the_same_floats() -> None:
    first = [math.cos(i) for i in range(v.DIMENSIONS)]
    assert v.pool(_first(first)) == v.pool(_first(first))


def test_pooling_refuses_a_first_token_of_385_dimensions() -> None:
    with pytest.raises(ValueError, match="384"):
        v.pool(_first([1.0] * 385))


def test_pooling_refuses_an_empty_first_token() -> None:
    with pytest.raises(ValueError, match="384"):
        v.pool([[]])


# --- the stored bytes (section 6, "Stored vector") ----------------


@pytest.mark.parametrize("i", range(v.DIMENSIONS))
def test_each_dimension_sets_exactly_its_own_bit(i: int) -> None:
    vector = [-1.0] * v.DIMENSIONS
    vector[i] = 1.0
    expected = bytearray(48)
    expected[i // 8] = 0x80 >> (i % 8)
    assert v.to_bits(vector) == bytes(expected)


def test_all_positive_gives_48_bytes_of_ff() -> None:
    assert v.to_bits([0.25] * v.DIMENSIONS) == b"\xff" * 48


def test_all_negative_gives_48_bytes_of_zero() -> None:
    assert v.to_bits([-0.25] * v.DIMENSIONS) == bytes(48)


def test_nan_is_not_greater_than_zero() -> None:
    assert v.to_bits([math.nan] * v.DIMENSIONS) == bytes(48)


def test_infinities_follow_their_sign() -> None:
    vector = [-math.inf] * v.DIMENSIONS
    vector[0] = math.inf
    assert v.to_bits(vector)[0] == 0x80
    assert v.to_bits([*vector[1:], math.inf])[47] == 0x01


def test_the_smallest_positive_float_is_greater_than_zero() -> None:
    tiny = struct.unpack("<d", struct.pack("<Q", 1))[0]  # 5e-324, subnormal
    assert v.to_bits([tiny] * v.DIMENSIONS) == b"\xff" * 48


def test_the_bits_come_back_as_bytes() -> None:
    assert type(v.to_bits([1.0] * v.DIMENSIONS)) is bytes


def test_bits_refuse_too_few_dimensions_and_none() -> None:
    with pytest.raises(ValueError, match="384"):
        v.to_bits([1.0] * 383)
    with pytest.raises(ValueError, match="384"):
        v.to_bits([])


def test_bits_take_any_sequence() -> None:
    assert v.to_bits(tuple([1.0] * v.DIMENSIONS)) == b"\xff" * 48


# --- the pinned files (section 6 table) ----------------


def test_the_embed_model_is_the_name_at_the_hash_of_the_model_file_not_the_tokenizer() -> None:
    model_hash = next(f.sha256 for f in v.MODEL.files if f.path == MODEL_REL)
    assert f"snowflake-arctic-embed-xs@{model_hash}" == v.EMBED_MODEL
    assert v.EMBED_MODEL.count("@") == 1


def test_a_hash_that_differs_in_one_digit_is_refused_naming_both(
    tmp_path: Path,
) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    good = hashlib.sha256(b"abc").hexdigest()
    flipped = ("0" if good[0] != "0" else "1") + good[1:]
    with pytest.raises(v.ModelFileError) as caught:
        v.check_file(path, v.PinnedFile("f", flipped))
    assert good in str(caught.value) and flipped in str(caught.value)


def test_a_directory_in_place_of_a_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "tokenizer.json").mkdir()
    with pytest.raises((v.ModelFileError, OSError)):
        v.check_file(tmp_path / "tokenizer.json", v.PinnedFile("tokenizer.json", "0" * 64))


def test_an_empty_file_is_refused_with_both_hashes(tmp_path: Path) -> None:
    path = tmp_path / "tokenizer.json"
    path.write_bytes(b"")
    with pytest.raises(v.ModelFileError) as caught:
        v.check_file(path, v.PinnedFile("tokenizer.json", "a" * 64))
    assert hashlib.sha256(b"").hexdigest() in str(caught.value)


def test_a_file_one_byte_longer_than_the_pinned_one_is_refused(tmp_path: Path) -> None:
    pinned = v.PinnedFile("f", hashlib.sha256(b"abc").hexdigest())
    path = tmp_path / "f"
    path.write_bytes(b"abc\n")
    with pytest.raises(v.ModelFileError):
        v.check_file(path, pinned)


def test_the_embedder_refuses_an_empty_directory_naming_a_pinned_file(tmp_path: Path) -> None:
    with pytest.raises(v.ModelFileError, match=r"model_quantized\.onnx|tokenizer\.json"):
        v.Embedder(tmp_path)


def test_the_embedder_refuses_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(v.ModelFileError):
        v.Embedder(tmp_path / "nowhere")


# --- fetching (plan M2.6, first item) ----------------


def _origin(tmp_path: Path, contents: dict[str, bytes]) -> str:
    root = tmp_path / "origin"
    for name, data in contents.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    return root.as_uri()


def _pinned(monkeypatch: pytest.MonkeyPatch, contents: dict[str, bytes]) -> None:
    files = tuple(v.PinnedFile(n, hashlib.sha256(d).hexdigest()) for n, d in contents.items())
    monkeypatch.setattr(fm, "MODEL", replace(v.MODEL, files=files))


def test_fetch_accepts_an_origin_with_a_trailing_slash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {"onnx/model.onnx": b"weights", "tokenizer.json": b"{}"}
    _pinned(monkeypatch, contents)
    dest = fm.fetch(tmp_path / "m", _origin(tmp_path, contents) + "/")
    assert (dest / "tokenizer.json").read_bytes() == b"{}"


def test_fetch_names_a_file_the_origin_does_not_have(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pinned(monkeypatch, {"tokenizer.json": b"{}"})
    origin = _origin(tmp_path, {"other.json": b"{}"})
    code = fm.main(["--dest", str(tmp_path / "m"), "--origin", origin])
    assert code != 0
    assert "tokenizer.json" in capsys.readouterr().err
    assert not (tmp_path / "m" / "tokenizer.json").exists()


def test_fetch_refuses_a_truncated_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = b"0123456789" * 100
    _pinned(monkeypatch, {"onnx/model.onnx": full})
    origin = _origin(tmp_path, {"onnx/model.onnx": full[:-1]})
    with pytest.raises(v.ModelFileError, match=r"onnx/model\.onnx"):
        fm.fetch(tmp_path / "m", origin)
    assert not (tmp_path / "m" / "onnx" / "model.onnx").exists()


def test_fetch_refuses_an_empty_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _pinned(monkeypatch, {"tokenizer.json": b"{}"})
    origin = _origin(tmp_path, {"tokenizer.json": b""})
    with pytest.raises(v.ModelFileError, match=r"tokenizer\.json"):
        fm.fetch(tmp_path / "m", origin)
    assert not (tmp_path / "m" / "tokenizer.json").exists()


def test_a_refused_file_does_not_leave_a_wrong_file_that_the_embedder_could_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pinned(monkeypatch, {"tokenizer.json": b"{}"})
    dest = tmp_path / "m"
    dest.mkdir()
    (dest / "tokenizer.json").write_bytes(b"stale")
    origin = _origin(tmp_path, {"tokenizer.json": b"wrong"})
    with pytest.raises(v.ModelFileError):
        fm.fetch(dest, origin)
    leftover = dest / "tokenizer.json"
    # Either the stale file is gone, or it still is exactly what it was; never the refused bytes.
    assert not leftover.exists() or leftover.read_bytes() == b"stale"
    assert not list(dest.rglob("*.part"))


def test_fetch_twice_gives_the_same_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    contents = {"onnx/model.onnx": b"weights", "tokenizer.json": b"{}"}
    _pinned(monkeypatch, contents)
    origin = _origin(tmp_path, contents)
    dest = tmp_path / "m"
    fm.fetch(dest, origin)
    fm.fetch(dest, origin)
    assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()) == [
        "onnx/model.onnx",
        "tokenizer.json",
    ]


def test_main_exits_0_when_everything_is_pinned_and_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {"tokenizer.json": b"{}"}
    _pinned(monkeypatch, contents)
    assert fm.main(["--dest", str(tmp_path / "m"), "--origin", _origin(tmp_path, contents)]) == 0


# --- the real model (slow) ----------------


@pytest.fixture(scope="module")
def model_dir() -> Path:
    return fm.fetch()


@pytest.fixture(scope="module")
def embedder(model_dir: Path) -> v.Embedder:
    return v.Embedder(model_dir)


@pytest.mark.slow
def test_the_fetched_files_have_the_hashes_of_section_6(model_dir: Path) -> None:
    got = {
        f.path: hashlib.sha256((model_dir / f.path).read_bytes()).hexdigest() for f in v.MODEL.files
    }
    assert got == {
        MODEL_REL: "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1",
        TOKENIZER_REL: "91f1def9b9391fdabe028cd3f3fcc4efd34e5d1f08c3bf2de513ebb5911a1854",
    }


@pytest.mark.slow
def test_a_second_embedder_gives_the_same_bits_as_the_first(
    model_dir: Path, embedder: v.Embedder
) -> None:
    text = v.node_text("Item", "a", "Item A", "The first item", "a,1,x")
    assert v.Embedder(model_dir).bits(text) == embedder.bits(text)
    assert v.Embedder(model_dir).embed(text) == embedder.embed(text)


@pytest.mark.slow
def test_bits_are_the_signs_of_the_embedding(embedder: v.Embedder) -> None:
    text = v.node_text("Item", "a", "Item A", "The first item", None)
    assert embedder.bits(text) == v.to_bits(embedder.embed(text))


@pytest.mark.slow
def test_the_embedding_is_the_pooling_of_the_first_token_of_the_model(
    embedder: v.Embedder,
) -> None:
    out = embedder.embed("hello world")
    assert len(out) == v.DIMENSIONS
    assert math.isclose(math.fsum(x * x for x in out), 1.0, rel_tol=1e-9)
    assert any(x > 0 for x in out) and any(x < 0 for x in out)


@pytest.mark.slow
def test_the_empty_text_can_be_embedded(embedder: v.Embedder) -> None:
    out = embedder.embed("")
    assert len(out) == v.DIMENSIONS
    assert len(embedder.bits("")) == 48


@pytest.mark.slow
def test_a_nul_character_and_non_latin_text_can_be_embedded(embedder: v.Embedder) -> None:
    for text in ("a\x00b", "日本語のテキスト", "\U0001f600" * 50):
        assert len(embedder.bits(text)) == 48


@pytest.mark.slow
def test_a_very_long_text_is_embedded_like_its_first_256_tokens(embedder: v.Embedder) -> None:
    head = "word " * 400
    assert embedder.bits(head) == embedder.bits(head + "x " * 100_000)


@pytest.mark.slow
def test_text_before_the_256_token_limit_does_change_the_embedding(embedder: v.Embedder) -> None:
    base = "alpha " * 100
    assert embedder.embed(base) != embedder.embed("beta " + base)


@pytest.mark.slow
def test_a_text_just_inside_and_just_past_the_limit(embedder: v.Embedder) -> None:
    # 254 words + [CLS] + [SEP] = 256 tokens: the last word still counts.
    inside = "word " * 253 + "alpha"
    assert embedder.embed(inside) != embedder.embed("word " * 253 + "omega")
    # 255 words: [CLS] + 255 + [SEP] > 256, so the 255th word is cut with the [SEP] kept.
    past = "word " * 254
    assert embedder.embed(past + "alpha") == embedder.embed(past + "omega")


@pytest.mark.slow
def test_the_query_is_embedded_after_the_prefix(embedder: v.Embedder) -> None:
    assert embedder.query("fish") == embedder.embed(v.QUERY_PREFIX + "fish")
    assert embedder.query("fish") != embedder.embed("fish")


@pytest.mark.slow
def test_an_empty_query_can_be_embedded(embedder: v.Embedder) -> None:
    assert len(embedder.query("")) == v.DIMENSIONS


@pytest.mark.slow
def test_the_embedder_refuses_a_model_file_with_one_flipped_byte(
    model_dir: Path, tmp_path: Path
) -> None:
    shutil.copytree(model_dir, tmp_path / "m")
    path = tmp_path / "m" / MODEL_REL
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(v.ModelFileError) as caught:
        v.Embedder(tmp_path / "m")
    assert MODEL_REL in str(caught.value)
    assert hashlib.sha256(bytes(data)).hexdigest() in str(caught.value)


@pytest.mark.slow
def test_the_embedder_refuses_a_tokenizer_with_another_hash(
    model_dir: Path, tmp_path: Path
) -> None:
    shutil.copytree(model_dir, tmp_path / "m")
    path = tmp_path / "m" / TOKENIZER_REL
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(v.ModelFileError, match=r"tokenizer\.json"):
        v.Embedder(tmp_path / "m")


@pytest.mark.slow
def test_the_embedder_refuses_a_missing_tokenizer(model_dir: Path, tmp_path: Path) -> None:
    shutil.copytree(model_dir, tmp_path / "m")
    (tmp_path / "m" / TOKENIZER_REL).unlink()
    with pytest.raises(v.ModelFileError, match=r"tokenizer\.json"):
        v.Embedder(tmp_path / "m")
