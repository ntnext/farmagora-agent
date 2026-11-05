"""Product photos found by code must sit where the hand-checked golden bboxes are (Oct–Nov 2026 cover)."""

from pathlib import Path

from flyer_agent.adapters.pdf import product_photos
from flyer_agent.core.models import FlyerData

FLYER = Path(__file__).resolve().parents[2] / "tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf"


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def test_photos_match_golden_bboxes(golden: FlyerData):
    photos = product_photos(FLYER)
    with_box = [p for p in golden.products if p.bbox]
    assert with_box
    for p in with_box:
        price = f"{p.price.current_eur:.2f}".replace(".", ",")
        cands = [ph["bbox"] for ph in photos if ph["page"] == p.page and ph["price"] == price]
        assert cands, f"no photo found for {p.name}"
        assert max(_iou(c, p.bbox) for c in cands) > 0.4, f"photo for {p.name} is elsewhere"
