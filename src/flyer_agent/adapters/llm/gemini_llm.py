"""Google Gemini adapter (official `google-genai` SDK). PDF sent inline, JSON response mode."""

from __future__ import annotations

import os

from pydantic import BaseModel

from ...ports.llm import Capabilities, ImagePart, Part, PdfPart, TextPart
from .base import BaseLLM, schema_instructions


class GeminiLLM(BaseLLM):
    provider = "gemini"

    def __init__(self, model: str, api_key_env: str = "GEMINI_API_KEY", **_):
        super().__init__(model, Capabilities(pdf_input=True, image_input=True, json_schema=False))
        from google import genai

        self.client = genai.Client(api_key=os.environ.get(api_key_env))

    def _call(self, system: str, prompt: str, inputs: list[Part], schema: type[BaseModel],
              temperature: float) -> tuple[str, int, int]:
        from google.genai import types

        contents: list = []
        for p in inputs:
            if isinstance(p, PdfPart):
                contents.append(types.Part.from_bytes(data=p.path.read_bytes(), mime_type="application/pdf"))
            elif isinstance(p, ImagePart):
                contents.append(types.Part.from_bytes(data=p.path.read_bytes(), mime_type=p.mime))
            elif isinstance(p, TextPart):
                contents.append(p.text)
        contents.append(prompt)
        resp = self.client.models.generate_content(
            model=self.model, contents=contents,
            config=types.GenerateContentConfig(system_instruction=system + "\n\n" + schema_instructions(schema),
                                               temperature=temperature, response_mime_type="application/json"),
        )
        um = resp.usage_metadata
        out_tokens = (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
        return resp.text or "", getattr(um, "prompt_token_count", 0) or 0, out_tokens  # thinking is billed as output
