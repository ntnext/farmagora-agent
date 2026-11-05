"""Load YAML config and .env. Paths are relative to the project root (cwd)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")  # KEY="value" and KEY='value' are common in .env files
            if v:
                os.environ.setdefault(k.strip(), v)


def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}


@dataclass
class Config:
    root: Path
    app: dict[str, Any]
    brand: dict[str, Any]
    compliance: dict[str, Any]
    channels: dict[str, Any]
    pricing: dict[str, Any]
    examples: list[dict[str, Any]] = field(default_factory=list)
    provider_override: str | None = None
    model_override: str | None = None

    @property
    def runs_dir(self) -> Path:
        return self.root / self.app.get("paths", {}).get("runs", "runs")

    def task(self, name: str) -> dict[str, Any]:
        t = dict(self.app["llm"]["tasks"][name])
        if self.provider_override:
            t["provider"] = self.provider_override
            t["model"] = self.model_override or (t["model"] if t["provider"] == self.provider_override else "")
            if self.provider_override == "offline":
                t["model"] = "rules-v1"
        return t


def load(root: Path | None = None, provider: str | None = None, model: str | None = None) -> Config:
    root = (root or Path.cwd()).resolve()
    _load_env(root / ".env")
    c = root / "config"
    ex = _yaml(c / "examples" / "captions.yaml")
    return Config(root=root, app=_yaml(c / "app.yaml"), brand=_yaml(c / "brand.yaml"),
                  compliance=_yaml(c / "compliance.yaml"), channels=_yaml(c / "channels.yaml"),
                  pricing=_yaml(c / "pricing.yaml"), examples=ex if isinstance(ex, list) else [],
                  provider_override=provider or os.environ.get("FLYER_PROVIDER"), model_override=model)
