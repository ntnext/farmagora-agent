"""LLM port: the only way core/stages talk to any model provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    path: Path
    mime: str = "image/png"


@dataclass(frozen=True)
class PdfPart:
    path: Path
    page_images: tuple[Path, ...] = ()  # fallback for models without PDF input


Part = TextPart | ImagePart | PdfPart


@dataclass(frozen=True)
class Capabilities:
    pdf_input: bool
    image_input: bool
    json_schema: bool
    max_images: int = 20


@dataclass
class LLMResult(Generic[T]):
    value: T
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    raw: str = field(default="", repr=False)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    provider: str
    model: str
    capabilities: Capabilities

    def structured(self, system: str, prompt: str, inputs: list[Part], schema: type[T],
                   temperature: float) -> LLMResult[T]: ...
