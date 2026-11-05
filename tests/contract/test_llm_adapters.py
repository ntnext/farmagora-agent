"""Every LLM adapter must honour the same contract. Real providers are checked offline (no network)."""

import pytest
from pydantic import BaseModel

from flyer_agent.adapters.llm.base import BaseLLM, parse_json
from flyer_agent.adapters.llm.registry import build_client
from flyer_agent.ports.llm import Capabilities, LLMError, LLMResult


class Thing(BaseModel):
    name: str
    qty: int


class Scripted(BaseLLM):
    provider = "scripted"

    def __init__(self, outputs):
        super().__init__("m", Capabilities(pdf_input=False, image_input=False, json_schema=False))
        self.outputs, self.prompts = list(outputs), []

    def _call(self, system, prompt, inputs, schema, temperature):
        self.prompts.append(prompt)
        return self.outputs.pop(0), 10, 5


def test_parse_json_strips_fences():
    assert parse_json('```json\n{"name": "a", "qty": 1}\n```') == {"name": "a", "qty": 1}


def test_retry_once_with_errors_then_succeed():
    llm = Scripted(['{"name": "a"}', '{"name": "a", "qty": 2}'])
    res = llm.structured("s", "p", [], Thing, 0)
    assert isinstance(res, LLMResult) and res.value.qty == 2
    assert res.input_tokens == 20 and "non era valida" in llm.prompts[1]


def test_fail_after_retry():
    with pytest.raises(LLMError):
        Scripted(["nope", "still nope"]).structured("s", "p", [], Thing, 0)


@pytest.mark.parametrize("provider,module", [
    ("anthropic", "anthropic"), ("openai", "openai"), ("gemini", "google.genai"),
    ("openai_compatible", "openai"), ("offline", None)])
def test_registry_builds_every_provider(provider, module, monkeypatch):
    if module:
        pytest.importorskip(module)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENAI_COMPATIBLE_API_KEY"):
        monkeypatch.setenv(k, "test")
    cfg = {"openai_compatible": {"base_url": "http://localhost:11434/v1"}}
    client = build_client(provider, "some-model", cfg)
    assert client.provider == provider and isinstance(client.capabilities, Capabilities)


class Busy(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"HTTP {code} {message}")
        self.code = code


class Flaky(Scripted):
    """Raises the given errors first, then answers."""

    def __init__(self, errors, outputs):
        super().__init__(outputs)
        self.errors, self.slept = list(errors), []
        self.sleep = self.slept.append

    def _call(self, system, prompt, inputs, schema, temperature):
        if self.errors:
            raise self.errors.pop(0)
        return super()._call(system, prompt, inputs, schema, temperature)


def test_transient_server_errors_are_retried_with_backoff():
    llm = Flaky([Busy(503), Busy(529)], ['{"name": "a", "qty": 1}'])
    assert llm.structured("s", "p", [], Thing, 0).value.qty == 1
    assert llm.slept == [10, 30]


def test_quota_errors_are_not_retried():
    llm = Flaky([Busy(429)], ['{"name": "a", "qty": 1}'])
    with pytest.raises(Busy):
        llm.structured("s", "p", [], Thing, 0)
    assert llm.slept == []


def test_per_minute_rate_limit_is_retried_daily_quota_is_not():
    llm = Flaky([Busy(429, "Rate limit reached on tokens per minute (TPM): Limit 8000")], ['{"name": "a", "qty": 1}'])
    assert llm.structured("s", "p", [], Thing, 0).value.qty == 1 and llm.slept == [10]
    daily = Flaky([Busy(429, "Generate content requests per day limit exceeded")], ['{"name": "a", "qty": 1}'])
    with pytest.raises(Busy):
        daily.structured("s", "p", [], Thing, 0)


class OpenAIStyle(Exception):
    """Like openai.RateLimitError: HTTP status in .status_code, a string in .code."""

    def __init__(self):
        super().__init__("Error code: 429 - Rate limit reached ... tokens per minute (TPM): Limit 8000")
        self.status_code, self.code = 429, "rate_limit_exceeded"


def test_openai_style_rate_limit_is_retried():
    llm = Flaky([OpenAIStyle()], ['{"name": "a", "qty": 1}'])
    assert llm.structured("s", "p", [], Thing, 0).value.qty == 1 and llm.slept == [10]


def test_gives_up_after_last_backoff():
    llm = Flaky([Busy(503)] * 4, ['{"name": "a", "qty": 1}'])
    with pytest.raises(Busy):
        llm.structured("s", "p", [], Thing, 0)
    assert llm.slept == [10, 30, 60]
