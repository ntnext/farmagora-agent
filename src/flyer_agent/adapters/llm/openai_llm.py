"""OpenAI adapter (official `openai` SDK, Chat Completions). Also the base for OpenAI-compatible APIs."""

from __future__ import annotations

import base64
import os

from pydantic import BaseModel

from ...ports.llm import Capabilities, ImagePart, LLMError, Part, PdfPart, TextPart
from .base import BaseLLM, schema_instructions


class OpenAILLM(BaseLLM):
    provider = "openai"

    def __init__(self, model: str, api_key_env: str = "OPENAI_API_KEY", base_url: str | None = None,
                 image_input: bool = True, max_tokens: int = 16000, max_images: int = 20, **_):
        super().__init__(model, Capabilities(pdf_input=False, image_input=image_input, json_schema=False,
                                             max_images=max_images))
        from openai import OpenAI

        self.client = OpenAI(api_key=os.environ.get(api_key_env) or "none", base_url=base_url)
        self.max_tokens = max_tokens

    def _content(self, prompt: str, inputs: list[Part]) -> list[dict]:
        parts: list[dict] = []
        for p in inputs:
            images = []
            if isinstance(p, PdfPart):  # no native PDF here: send the rendered pages
                images = [ImagePart(path=x) for x in p.page_images]
                if not images:
                    raise LLMError("PDF given but no page images rendered (run ingest)")
            elif isinstance(p, ImagePart):
                images = [p]
            elif isinstance(p, TextPart):
                parts.append({"type": "text", "text": p.text})
            for im in images:
                if not self.capabilities.image_input:
                    raise LLMError(f"{self.model} has no image input: cannot read the flyer")
                b64 = base64.b64encode(im.path.read_bytes()).decode()
                parts.append({"type": "image_url", "image_url": {"url": f"data:{im.mime};base64,{b64}"}})
        parts.append({"type": "text", "text": prompt})
        return parts

    def _call(self, system: str, prompt: str, inputs: list[Part], schema: type[BaseModel],
              temperature: float) -> tuple[str, int, int]:
        resp = self.client.chat.completions.create(
            model=self.model, temperature=temperature, max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system + "\n\n" + schema_instructions(schema)},
                      {"role": "user", "content": self._content(prompt, inputs)}],
        )
        u = resp.usage
        return resp.choices[0].message.content or "", getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0)


class OpenAICompatibleLLM(OpenAILLM):
    """Mistral, Groq, Together, Ollama, vLLM... anything speaking the OpenAI Chat Completions API."""

    provider = "openai_compatible"

    def __init__(self, model: str, base_url: str, api_key_env: str = "OPENAI_COMPATIBLE_API_KEY",
                 image_input: bool = True, **kw):
        super().__init__(model, api_key_env=api_key_env, base_url=base_url, image_input=image_input, **kw)
