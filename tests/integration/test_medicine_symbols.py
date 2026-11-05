"""Medicine symbols found by code in the real Oct–Nov 2026 flyer must match the hand-checked golden file."""

from pathlib import Path

from flyer_agent.adapters.pdf import medicine_symbols
from flyer_agent.core.models import FlyerData

FLYER = Path(__file__).resolve().parents[2] / "tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf"


def _eur(v) -> str | None:
    return None if v is None else f"{v:.2f}".replace(".", ",")


def test_symbols_found_in_pdf_match_golden_medicines(golden: FlyerData):
    """Each symbol is paired with the new or the struck price of a golden medicine, and every medicine has one."""
    found = {(s["page"], s["price"]) for s in medicine_symbols(FLYER) if s["price"]}
    meds = [p for p in golden.products if p.is_medicine]
    keys = {p.id: {(p.page, _eur(p.price.current_eur)), (p.page, _eur(p.price.previous_eur))} for p in meds}
    assert all(any(f in k for k in keys.values()) for f in found), "symbol paired with a non-medicine price"
    assert all(k & found for k in keys.values()), "medicine without a symbol"
