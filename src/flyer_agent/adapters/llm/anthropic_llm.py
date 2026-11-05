"""Anthropic Claude adapter (official `anthropic` SDK). Structured output via a forced tool call."""

from __future__ import annotations

import base64
import json
import os

from pydantic import BaseModel

from ...ports.llm import Capabilities, ImagePart, Part, PdfPart, TextPart
from .base import BaseLLM


class AnthropicLLM(BaseLLM):
    provider = "anthropic"

    def __init__(self, model: str, api_key_env: str = "ANTHROPIC_API_KEY", max_tokens: int = 16000, **_):
        super().__init__(model, Capabilities(pdf_input=True, image_input=True, json_schema=True))
        import anthropic

        self.client = anthropic.Anthropic(api_key=os.environ.get(api_key_env))
        self.max_tokens = max_tokens

    def _content(self, prompt: str, inputs: list[Part]) -> list[dict]:
        blocks: list[dict] = []
        for p in inputs:
            if isinstance(p, PdfPart):
                blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                              "data": base64.b64encode(p.path.read_bytes()).decode()}})
            elif isinstance(p, ImagePart):
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": p.mime,
                                                           "data": base64.b64encode(p.path.read_bytes()).decode()}})
            elif isinstance(p, TextPart):
                blocks.append({"type": "text", "text": p.text})
        blocks.append({"type": "text", "text": prompt})
        return blocks

    def _call(self, system: str, prompt: str, inputs: list[Part], schema: type[BaseModel],
              temperature: float) -> tuple[str, int, int]:
        tool = {"name": "emit_result", "description": f"Return the {schema.__name__} object.",
                "input_schema": schema.model_json_schema()}
        msg = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, temperature=temperature, system=system,
            tools=[tool], tool_choice={"type": "tool", "name": "emit_result"},
            messages=[{"role": "user", "content": self._content(prompt, inputs)}],
        )
        data = next((b.input for b in msg.content if getattr(b, "type", "") == "tool_use"), None)
        raw = json.dumps(data, ensure_ascii=False) if data is not None else ""
        return raw, msg.usage.input_tokens, msg.usage.output_tokens
