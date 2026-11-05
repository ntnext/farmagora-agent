from pathlib import Path

import pytest

from flyer_agent.core.models import FlyerData

ROOT = Path(__file__).resolve().parents[1]
FLYER = ROOT / "tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf"


@pytest.fixture
def golden() -> FlyerData:
    return FlyerData.model_validate_json(FLYER.with_suffix(".golden.json").read_text(encoding="utf-8"))
