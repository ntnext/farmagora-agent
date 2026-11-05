"""Models with few images per request read the flyer in page batches; the merged result equals one full read."""

import shutil
from pathlib import Path

from flyer_agent import config
from flyer_agent.core.models import FlyerData
from flyer_agent.ports.llm import Capabilities, LLMResult, PdfPart
from flyer_agent.stages import pipeline as P

ROOT = Path(__file__).resolve().parents[2]
FLYER = ROOT / "tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf"


class ThreeImageModel:
    """Fake vision model: max 3 images; 'reads' only the golden products on the pages it is shown."""

    provider, model = "fake", "three-images"
    capabilities = Capabilities(pdf_input=False, image_input=True, json_schema=False, max_images=3)

    def __init__(self, golden: FlyerData):
        self.golden, self.calls = golden, []

    def structured(self, system, prompt, inputs, schema, temperature):
        pdf = next(p for p in inputs if isinstance(p, PdfPart))
        assert len(pdf.page_images) <= 3
        pages = {int(p.stem.split("-")[1]) for p in pdf.page_images}
        self.calls.append(sorted(pages))
        part = self.golden.model_copy(deep=True)
        part.products = [p for p in part.products if p.page in pages]
        part.promotions = [p for p in part.promotions if p.page in pages]
        part.services = [s for s in part.services if s.page in pages]
        return LLMResult(value=part, provider=self.provider, model=self.model, input_tokens=100, output_tokens=50)


def test_batched_extract_matches_golden(tmp_path, golden, monkeypatch):
    for d in ("config", "prompts", "templates", "assets"):
        shutil.copytree(ROOT / d, tmp_path / d)
    cfg = config.load(tmp_path, provider="offline")
    fake = ThreeImageModel(golden)
    monkeypatch.setattr(P, "_client", lambda cfg, task: (fake, {"temperature": 0}))
    run = P.ingest(cfg, FLYER)
    data, _ = P.extract(run)
    assert fake.calls == [[1, 2, 3], [4, 5, 6], [7, 8]]
    assert [p.id for p in data.products] == [p.id for p in golden.products]
    assert len(data.services) == len(golden.services) and len(data.promotions) == len(golden.promotions)
    call = run.manifest.llm_calls[-1]
    assert (call.input_tokens, call.output_tokens) == (300, 150)  # one record for the whole read
