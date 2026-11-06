"""The embedding model, node and query text, pooling and stored bits (Specification 0.1, 6).

Section 6: "Format 0.1 defines one embedding model. A mosaic's vectors MUST be made by the
mosaic builder, natively, with this exact model file." Section 3.7: "`embed_model` names the
model and the SHA-256 of its exact model file, as `<name>@<file hash>`."

These tests need no model: they check the text that is embedded, the pooling of the model's
output and the packing of its signs into the 48 stored bytes.
"""

import hashlib
import math
from pathlib import Path

import pytest
from mosaic_build.mosaic import vectors as v

MODEL_FILE_HASH = "e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1"
TOKENIZER_HASH = "91f1def9b9391fdabe028cd3f3fcc4efd34e5d1f08c3bf2de513ebb5911a1854"


# --- the model of section 6 ----------------------------------------------------------------


def test_embed_model_is_the_full_value_of_section_6() -> None:
    full = (
        "snowflake-arctic-embed-xs@e6aa5e656466a73d7c3111e9a3378bd13e5b93af30eaac2b3f13fd56692589a1"
    )
    assert full == v.EMBED_MODEL


def test_the_model_and_tokenizer_files_are_pinned_by_hash() -> None:
    assert v.MODEL.repository == "Snowflake/snowflake-arctic-embed-xs"
    assert v.MODEL.revision == "d8c86521100d3556476a063fc2342036d45c106f"
    assert v.MODEL.licence == "Apache-2.0"
    files = {f.path: f.sha256 for f in v.MODEL.files}
    assert files == {"onnx/model_quantized.onnx": MODEL_FILE_HASH, "tokenizer.json": TOKENIZER_HASH}
    assert v.MAX_TOKENS == 256
    assert v.DIMENSIONS == 384


def test_embed_model_names_the_model_file_hash_in_the_form_of_section_3_7() -> None:
    name, _, file_hash = v.EMBED_MODEL.partition("@")
    assert name and len(file_hash) == 64
    assert file_hash == next(f.sha256 for f in v.MODEL.files if f.path.endswith(".onnx"))


# --- a model file is checked by its hash ----------------------------------------------------


def test_a_file_with_its_pinned_hash_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "model.onnx"
    path.write_bytes(b"model bytes")
    pinned = v.PinnedFile("onnx/model.onnx", hashlib.sha256(b"model bytes").hexdigest())
    assert v.check_file(path, pinned) == path


def test_a_file_with_another_hash_is_refused_naming_the_file_and_both_hashes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "model_quantized.onnx"
    path.write_bytes(b"another file of the same model")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    pinned = v.PinnedFile("onnx/model_quantized.onnx", MODEL_FILE_HASH)
    with pytest.raises(v.ModelFileError) as caught:
        v.check_file(path, pinned)
    message = str(caught.value)
    assert str(path) in message
    assert "onnx/model_quantized.onnx" in message
    assert MODEL_FILE_HASH in message and actual in message


def test_a_missing_file_is_refused_naming_it(tmp_path: Path) -> None:
    pinned = v.PinnedFile("tokenizer.json", TOKENIZER_HASH)
    with pytest.raises(v.ModelFileError, match=r"tokenizer\.json"):
        v.check_file(tmp_path / "tokenizer.json", pinned)


# --- the text that is embedded ----------------------------------------------------------------


def test_node_text_is_type_key_label_summary_snippet() -> None:
    text = v.node_text("Item", "a", "Item A", "The first item", "a,1,x")
    assert text == "Item a: Item A. The first item a,1,x"


def test_an_absent_summary_and_snippet_are_empty_strings() -> None:
    assert v.node_text("Item", "a", "Item A", None, None) == "Item a: Item A.  "
    assert v.node_text("Item", "a", "Item A", None, "a,1,x") == "Item a: Item A.  a,1,x"
    assert v.node_text("Item", "a", "Item A", "First", None) == "Item a: Item A. First "


def test_the_snippet_is_cut_to_its_first_800_characters() -> None:
    snippet = "é" * 799 + "xyz"
    text = v.node_text("Item", "a", "Item A", None, snippet)
    assert text == "Item a: Item A.  " + "é" * 799 + "x"


def test_text_is_kept_as_it_is_otherwise() -> None:
    text = v.node_text("Item", "a b", "  Item\nA ", "x\ty", "  s  ")
    assert text == "Item a b:   Item\nA . x\ty   s  "


def test_query_text_has_the_prefix_of_section_6() -> None:
    assert v.QUERY_PREFIX == "Represent this sentence for searching relevant passages: "
    assert v.query_text("where is item A?") == (
        "Represent this sentence for searching relevant passages: where is item A?"
    )


# --- pooling and stored bits -------------------------------------------------------------------


def _output(first: list[float]) -> list[list[float]]:
    """A model output for three tokens whose first token is ``first``."""
    return [first, [9.0] * len(first), [-9.0] * len(first)]


def test_the_embedding_is_the_first_tokens_output_divided_by_its_norm() -> None:
    first = [3.0, -4.0] + [0.0] * (v.DIMENSIONS - 2)
    vector = v.pool(_output(first))
    assert vector[:2] == [0.6, -0.8]
    assert all(x == 0.0 for x in vector[2:])
    assert math.isclose(math.fsum(x * x for x in vector), 1.0)


def test_pooling_refuses_an_output_of_another_size() -> None:
    with pytest.raises(ValueError, match="384"):
        v.pool(_output([1.0] * 383))
    with pytest.raises(ValueError, match="no token"):
        v.pool([])


def test_pooling_refuses_a_zero_vector() -> None:
    with pytest.raises(ValueError, match="norm"):
        v.pool(_output([0.0] * v.DIMENSIONS))


def test_bit_i_is_set_when_dimension_i_is_greater_than_0_msb_of_byte_0_first() -> None:
    vector = [-1.0] * v.DIMENSIONS
    vector[0] = 0.5  # byte 0, most significant bit
    vector[9] = 0.1  # byte 1, second bit
    vector[383] = 2.0  # byte 47, least significant bit
    bits = v.to_bits(vector)
    assert len(bits) == 48
    assert bits[0] == 0b1000_0000
    assert bits[1] == 0b0100_0000
    assert bits[47] == 0b0000_0001
    assert bits[2:47] == bytes(45)


def test_zero_is_not_greater_than_zero() -> None:
    assert v.to_bits([0.0] * v.DIMENSIONS) == bytes(48)
    assert v.to_bits([-0.0] * v.DIMENSIONS) == bytes(48)
    assert v.to_bits([1e-30] * v.DIMENSIONS) == b"\xff" * 48


def test_bits_need_384_dimensions() -> None:
    with pytest.raises(ValueError, match="384"):
        v.to_bits([1.0] * 385)


def test_pooled_bits_of_a_model_output() -> None:
    first = [(-1.0) ** i * (i + 1) for i in range(v.DIMENSIONS)]  # +, -, +, - …
    assert v.to_bits(v.pool(_output(first))) == b"\xaa" * 48


# --- which snippet: the first in evid order (answer on #105, reading A) ------------------------


def test_the_node_text_takes_the_first_snippet_of_the_node_in_evid_order() -> None:
    snippets = [(2, "size 1"), (1, "a,1,x")]
    assert v.first_snippet(snippets) == "a,1,x"
    text = v.node_text("Item", "a", "Item A", None, v.first_snippet(snippets))
    assert text == "Item a: Item A.  a,1,x"


def test_a_node_without_snippets_embeds_the_empty_string() -> None:
    assert v.first_snippet([]) is None
    assert v.node_text("Item", "a", "Item A", None, v.first_snippet([])) == "Item a: Item A.  "


def test_a_null_label_is_the_empty_string() -> None:
    # Answer on #105: a NULL label embeds the empty string, as for summary and snippet.
    assert v.node_text("Item", "a", None, None, "a,1,x") == "Item a: .  a,1,x"
    assert v.node_text("Item", "a", None, None, None) == "Item a: .  "
