"""`flyer eval` / `flyer score`: extraction accuracy vs the golden files, per provider, as a markdown scorecard."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..core.models import FlyerData
from ..core.scoring import CORE_TARGET_PCT, ExtractionScore, score_extraction
from . import pipeline as P

GOLDEN_GLOB = "tests/fixtures/flyers/*.golden.json"


def golden_flyers(cfg: Config) -> list[tuple[Path, Path]]:
    """(pdf, golden json) pairs with a hand-checked golden file. Drafts (*.golden.draft.json) are skipped."""
    out = []
    for g in sorted(cfg.root.glob(GOLDEN_GLOB)):
        pdf = g.with_name(g.name.replace(".golden.json", ".pdf"))
        if pdf.exists():
            out.append((pdf, g))
    return out


def golden_for(cfg: Config, flyer_id: str) -> Path | None:
    """Golden file whose PDF has this SHA-256 (the run's flyer_id)."""
    for pdf, g in golden_flyers(cfg):
        if hashlib.sha256(pdf.read_bytes()).hexdigest() == flyer_id:
            return g
    return None


def score_run(run: P.Run, golden: Path) -> ExtractionScore:
    got = run.load("flyer_data.json", FlyerData)
    return score_extraction(got, FlyerData.model_validate_json(golden.read_text(encoding="utf-8")))


def _eval_cfg(cfg: Config, provider: str, model: str | None) -> Config:
    """Same config, one provider for every task, runs kept apart in runs/eval/<provider>-<model>/."""
    tag = f"{provider}-{model or 'default'}"
    runs = str(Path(cfg.app.get("paths", {}).get("runs", "runs")) / "eval" / tag)
    app = {**cfg.app, "paths": {**cfg.app.get("paths", {}), "runs": runs}}
    return dataclasses.replace(cfg, app=app, provider_override=provider, model_override=model)


def evaluate(cfg: Config, providers: list[str]) -> Path:
    """Run `extract` on every golden flyer with each `provider[:model]`, score it and write the scorecard."""
    rows: list[str] = []
    for spec in providers:
        provider, _, model = spec.partition(":")
        ecfg = _eval_cfg(cfg, provider, model or None)
        for pdf, golden in golden_flyers(cfg):
            run = P.ingest(ecfg, pdf)
            try:
                P.extract(run)
            except Exception as e:  # noqa: BLE001 - one failing provider must not stop the comparison
                rows.append(f"| {pdf.stem} | {spec} | error: {str(e)[:80]} |" + " |" * 8)
                continue
            rows.append(_row(pdf.stem, spec, score_run(run, golden), run))
    return _write(cfg, rows)


def _row(flyer: str, spec: str, s: ExtractionScore, run: P.Run) -> str:
    call = next((c for c in reversed(run.manifest.llm_calls) if c.task == "extract"), None)
    cost = f"€{call.cost_eur:.3f}" if call else "-"
    secs = f"{call.latency_s:.0f}s" if call else "-"
    return (f"| {flyer} | {spec} | {s.matched}/{s.products_golden} (+{len(s.extra)}) | {s.core_pct}% | "
            f"{s.pct('prices')}% | {len(s.medicine_errors)} | {s.pct('product_type')}% | "
            f"{s.promotions[0]}/{s.promotions[1]} · {s.services[0]}/{s.services[1]} | {cost} | {secs} | "
            f"{'✅' if s.passed else '❌'} |")


def _write(cfg: Config, rows: list[str]) -> Path:
    out = cfg.root / "tests" / "eval" / f"scorecard-{datetime.now():%Y-%m-%d-%H%M}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    head = ("| Flyer | Provider | Products found | Name+prices+badges exact | Prices | Medicine errors | "
            "Product type | Promos · services | Cost | Time | M1 pass |\n|---|---|---|---|---|---|---|---|---|---|---|")
    out.write_text(f"# Extraction scorecard ({datetime.now():%Y-%m-%d %H:%M})\n\n"
                   f"Pass = ≥{CORE_TARGET_PCT}% exact on name + prices + badges, dates right, all promotions, "
                   f"services and loyalty found, no medicine errors.\n\n{head}\n" + "\n".join(rows) + "\n",
                   encoding="utf-8")
    return out
