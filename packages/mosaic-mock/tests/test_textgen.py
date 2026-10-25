from __future__ import annotations

import logging

import pytest
from mosaic_mock import profiles
from mosaic_mock.engine.generate import generate
from mosaic_mock.engine.text import TOKEN
from mosaic_mock.engine.textgen import AnthropicProvider


class Echo:
    """A provider that reorders sentences but keeps every token."""

    name = "echo"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        text = prompt.split("Paragraph:\n", 1)[1]
        return "In short: " + text


class Lossy:
    name = "lossy"

    def complete(self, prompt: str) -> str:
        text = prompt.split("Paragraph:\n", 1)[1]
        return TOKEN.sub("something", text)


@pytest.mark.req("MOCK-20")
def test_templates_need_no_provider() -> None:
    gen = generate(profiles.get("spacecraft"))
    assert gen.truth["llm"] is None


@pytest.mark.req("MOCK-21")
def test_rewrite_keeps_references_and_ground_truth(tmp_path) -> None:
    gen = generate(profiles.get("spacecraft"), llm=Echo(), cache_dir=tmp_path)
    assert gen.truth["llm"] == "echo"
    assert gen.files["sum/sum.pdf"] != generate(profiles.get("spacecraft")).files["sum/sum.pdf"]
    clean = generate(profiles.get("spacecraft"))

    def exact(g) -> list:
        return sorted((m["item"], m["role"]) for m in g.truth["mentions"] if m["match"] == "exact")

    assert exact(gen) == exact(clean)


@pytest.mark.req("MOCK-21")
def test_lost_tokens_fall_back_to_the_template(tmp_path, caplog) -> None:
    caplog.set_level(logging.WARNING)
    gen = generate(profiles.get("spacecraft"), llm=Lossy(), cache_dir=tmp_path)
    clean = generate(profiles.get("spacecraft"))
    assert gen.files["sum/sum.pdf"] == clean.files["sum/sum.pdf"]
    assert "keeping the template text" in caplog.text


@pytest.mark.req("MOCK-22")
def test_responses_are_cached_by_prompt_hash(tmp_path) -> None:
    echo = Echo()
    generate(profiles.get("spacecraft"), llm=echo, cache_dir=tmp_path)
    first = echo.calls
    assert first > 0
    assert list((tmp_path / "spacecraft").glob("*.txt"))
    again = Echo()
    generate(profiles.get("spacecraft"), llm=again, cache_dir=tmp_path)
    assert again.calls == 0


@pytest.mark.req("MOCK-22")
def test_anthropic_provider_shape() -> None:
    class Block:
        type = "text"
        text = " rewritten "

    class Response:
        stop_reason = "end_turn"
        content = (Block(),)

    class Messages:
        def create(self, **kw):
            assert kw["model"] == "claude-opus-5-5"
            assert kw["fallbacks"] == "default"
            return Response()

    class Beta:
        messages = Messages()

    class Client:
        beta = Beta()

    assert AnthropicProvider(client=Client()).complete("x") == "rewritten"
    Response.stop_reason = "refusal"
    assert AnthropicProvider(client=Client()).complete("x") is None
