"""Prose from Jinja templates, optionally rewritten by an LLM (MOCK-20…22).

Templates are the default: offline, deterministic, no API key. With a provider, each
paragraph is sent with its references as protected tokens (``⟦PCF/PWRT0012:id⟧``). A
rewrite that loses or alters any token is discarded and the template text kept. Responses
are cached by prompt hash, so a generation with ``--llm`` is reproducible offline.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from pathlib import Path
from typing import Protocol

import jinja2

from mosaic_mock.engine.text import tokens_in

log = logging.getLogger(__name__)

PROMPT = """Rewrite the paragraph below so it reads like a real spacecraft software user \
manual written by an engineer. Keep the meaning and keep it about the same length.
Every token of the form ⟦...⟧ must appear in your answer exactly as written, the same \
number of times; do not add new tokens. Answer with the paragraph only.

Paragraph:
{text}"""


class LlmProvider(Protocol):
    name: str

    def complete(self, prompt: str) -> str | None: ...


class AnthropicProvider:
    """Claude through the official SDK (optional extra ``mosaic-mock[llm]``).

    Only invented data is ever sent (MOCK-22). A refused or failed request returns
    ``None`` and the template text is kept.
    """

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5-5", client: object | None = None) -> None:
        if client is None:
            import anthropic  # ty: ignore[unresolved-import] - optional extra mosaic-mock[llm]

            client = anthropic.Anthropic()
        self._client = client
        self.model = model

    def complete(self, prompt: str) -> str | None:
        response = self._client.beta.messages.create(  # ty: ignore[unresolved-attribute] - SDK client
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            return None
        return "".join(b.text for b in response.content if b.type == "text").strip()


PROVIDERS: dict[str, type] = {"anthropic": AnthropicProvider}


class TextGen:
    def __init__(
        self,
        template_dir: Path,
        provider: LlmProvider | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(template_dir),
            undefined=jinja2.StrictUndefined,
            keep_trailing_newline=False,
            trim_blocks=False,
            lstrip_blocks=True,
            autoescape=False,  # plain text; serializers escape per format
        )
        self.provider = provider
        self.cache_dir = cache_dir
        self.rejected = 0

    def render(self, template: str, **ctx: object) -> str:
        """Template text, never rewritten (code, tables, headings)."""
        return self.env.get_template(template).render(**ctx).strip()

    def prose(self, template: str, **ctx: object) -> list[str]:
        """Paragraphs of prose, one per blank-line-separated block, optionally rewritten."""
        text = self.render(template, **ctx)
        paras = [" ".join(p.split()) for p in text.split("\n\n") if p.strip()]
        return [self.rewrite(p) for p in paras]

    def rewrite(self, text: str) -> str:
        if self.provider is None:
            return text
        prompt = PROMPT.format(text=text)
        answer = self._cached(prompt)
        if answer is None or Counter(tokens_in(answer)) != Counter(tokens_in(text)):
            self.rejected += 1
            log.warning("LLM rewrite lost or altered a reference; keeping the template text")
            return text
        return " ".join(answer.split())

    def _cached(self, prompt: str) -> str | None:
        assert self.provider is not None
        key = hashlib.sha256(f"{self.provider.name}\n{prompt}".encode()).hexdigest()
        path = self.cache_dir / f"{key}.txt" if self.cache_dir else None
        if path and path.exists():
            return path.read_text(encoding="utf-8")
        answer = self.provider.complete(prompt)
        if path and answer is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(answer, encoding="utf-8")
        return answer
