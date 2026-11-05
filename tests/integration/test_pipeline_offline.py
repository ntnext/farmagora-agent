"""Full pipeline on the Oct–Nov 2026 fixture with the offline provider (no API key, no network)."""

import csv
import shutil
from pathlib import Path

import pytest

from flyer_agent import config
from flyer_agent.core.state import StateError
from flyer_agent.ports.llm import LLMError
from flyer_agent.stages import pipeline as P

ROOT = Path(__file__).resolve().parents[2]
FLYER = ROOT / "tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf"


@pytest.fixture
def cfg(tmp_path):
    for d in ("config", "prompts", "templates", "assets", "tests/fixtures/flyers"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return config.load(tmp_path, provider="offline")


def test_end_to_end(cfg):
    run = P.ingest(cfg, FLYER)
    data, issues = P.extract(run)
    assert len(data.products) == 51 and not [i for i in issues if i.severity == "blocking"]
    with pytest.raises(StateError):
        P.generate(run)  # gate 1 not approved yet
    P.approve(run, "data", "test", "")
    pack = P.generate(run)
    assert all(p.caption_final for p in pack.posts)
    assert "€" not in "".join(p.copy_.caption for p in pack.posts)  # numbers only from code
    rep = P.check(run)
    assert not rep.blocking
    pytest.importorskip("playwright")
    files = P.render(run)
    assert len(files) == len(pack.posts) + len(pack.screens)
    rows = list(csv.reader((run.path("out/calendar.csv")).open(encoding="utf-8"), delimiter=";"))
    assert rows[0][0] == "data" and len(rows) == len(pack.posts) + 1
    P.approve(run, "pack", "test", "")
    z = P.export(run)
    assert z.exists() and run.manifest.state == "EXPORTED"


def test_unknown_flyer_offline_extract_fails_clearly(cfg, tmp_path):
    other = ROOT / "tests/fixtures/flyers/2026-05_maggio_salute-e-risparmio.pdf"
    run = P.ingest(cfg, other)
    with pytest.raises(LLMError, match="no recorded data"):
        P.extract(run)
