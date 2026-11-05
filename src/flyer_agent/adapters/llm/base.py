"""Shared logic for every provider: schema prompt, JSON parsing, validation, one retry."""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError

from ...ports.llm import Capabilities, LLMError, LLMResult, Part, T

FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
log = logging.getLogger("flyer_agent.llm")
TRANSIENT_STATUS = {500, 502, 503, 504, 529}  # server busy/overloaded: worth retrying
RETRY_DELAYS_S = (10, 30, 60)
PER_MINUTE_RE = re.compile(r"per minute|\b[TR]PM\b", re.IGNORECASE)


def is_transient(exc: Exception) -> bool:
    """True for vendor errors that usually pass on retry: HTTP 5xx / overloaded, and 429 for a *per-minute* rate
    limit (free tiers). A 429 for a daily or billing quota is not retried. Vendor-neutral."""
    # Gemini puts the HTTP status in `.code`; OpenAI-style SDKs use `.status_code` (their `.code` is a string).
    code = next((c for c in (getattr(exc, "status_code", None), getattr(exc, "code", None)) if isinstance(c, int)),
                None)
    if code is None:
        return False
    return code in TRANSIENT_STATUS or (code == 429 and bool(PER_MINUTE_RE.search(str(exc))))


def schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "Rispondi SOLO con un oggetto JSON valido che rispetti questo JSON Schema, "
        "senza testo prima o dopo e senza blocchi di codice.\n\nJSON Schema:\n"
        + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )


def parse_json(text: str) -> dict:
    cleaned = FENCE_RE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("no JSON object in model output")
    return json.loads(cleaned[start : end + 1])


class BaseLLM(ABC):
    provider = "base"

    def __init__(self, model: str, capabilities: Capabilities):
        self.model = model
        self.capabilities = capabilities
        self.sleep = time.sleep  # replaced in tests

    def _call_with_retry(self, system: str, prompt: str, inputs: list[Part], schema: type[BaseModel],
                         temperature: float) -> tuple[str, int, int]:
        """Call the vendor, retrying temporary server errors with back-off (RETRY_DELAYS_S)."""
        for delay in (*RETRY_DELAYS_S, None):
            try:
                return self._call(system, prompt, inputs, schema, temperature)
            except Exception as e:
                if delay is None or not is_transient(e):
                    raise
                log.warning(json.dumps({"event": "llm_retry", "provider": self.provider, "model": self.model,
                                        "error": str(e)[:200], "retry_in_s": delay}))
                self.sleep(delay)
        raise AssertionError("unreachable")

    @abstractmethod
    def _call(self, system: str, prompt: str, inputs: list[Part], schema: type[BaseModel],
              temperature: float) -> tuple[str, int, int]:
        """Return (raw_json_text, input_tokens, output_tokens)."""

    def structured(self, system: str, prompt: str, inputs: list[Part], schema: type[T],
                   temperature: float) -> LLMResult[T]:
        t0, tin, tout = time.time(), 0, 0
        attempt_prompt = prompt
        last_err: Exception | None = None
        for _ in range(2):  # first try + one retry with the errors
            raw, i, o = self._call_with_retry(system, attempt_prompt, inputs, schema, temperature)
            tin, tout = tin + i, tout + o
            try:
                value = schema.model_validate(parse_json(raw))
                return LLMResult(value=value, provider=self.provider, model=self.model, input_tokens=tin,
                                 output_tokens=tout, latency_s=round(time.time() - t0, 2), raw=raw)
            except (ValidationError, LLMError, json.JSONDecodeError) as e:
                last_err = e
                attempt_prompt = (prompt + "\n\nLa risposta precedente non era valida. Errori:\n"
                                  + str(e)[:3000] + "\nCorreggi e restituisci SOLO il JSON.")
        raise LLMError(f"{self.provider}/{self.model}: invalid output after retry: {last_err}")
