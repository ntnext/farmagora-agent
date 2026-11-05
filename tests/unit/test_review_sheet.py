"""Review spreadsheet: rows built from the data, approver edits applied back (pure)."""

from decimal import Decimal

import pytest

from flyer_agent.core import review_sheet as RS
from flyer_agent.core.models import FlyerData
from flyer_agent.core.validation import validate


def _rows(data: FlyerData) -> list[dict]:
    return [dict(zip(RS.PRODUCT_HEADERS, r, strict=True)) for r in RS.product_rows(data, [])]


@pytest.mark.parametrize(("raw", "want"), [("9,69", "9.69"), ("€ 9,69", "9.69"), ("9.69", "9.69"), (9.69, "9.69"),
                                           ("1.234,50", "1234.50"), ("", None)])
def test_parse_eur(raw, want):
    assert RS.parse_eur(raw) == (Decimal(want) if want else None)


@pytest.mark.parametrize(("raw", "want"), [("25", 25), ("-25%", 25), (25, 25), (0.25, 25), ("", None)])
def test_parse_pct(raw, want):
    assert RS.parse_pct(raw) == want


def test_unchanged_sheet_changes_nothing(golden: FlyerData):
    edits = RS.apply_product_rows(golden, _rows(golden))
    assert edits.changes == [] and edits.errors == []
    assert edits.data == golden


def test_price_edit_is_applied_and_checked_again(golden: FlyerData):
    rows = _rows(golden)
    rows[0][RS.P_PRICE] = "1,00"
    edits = RS.apply_product_rows(golden, rows)
    assert edits.data.products[0].price.current_eur == Decimal("1.00")
    assert "prezzo" in edits.changes[0] and "→ 1,00" in edits.changes[0]
    assert golden.products[0].price.current_eur != Decimal("1.00")  # input untouched
    assert any(i.severity == "blocking" for i in validate(edits.data))  # wrong edit is caught like a wrong reading


def test_medicine_flag_keeps_type_consistent(golden: FlyerData):
    rows = _rows(golden)
    i = next(n for n, p in enumerate(golden.products) if p.product_type != "farmaco")
    rows[i][RS.P_MED] = "sì"
    p = RS.apply_product_rows(golden, rows).data.products[i]
    assert p.is_medicine and p.product_type == "farmaco"


def test_unreadable_cells_are_reported_not_applied(golden: FlyerData):
    rows = _rows(golden)
    rows[0][RS.P_PRICE] = "nove euro"
    rows[1][RS.P_MED] = "forse"
    rows.append({RS.P_ID: "non-esiste", RS.P_PRICE: "1"})
    edits = RS.apply_product_rows(golden, rows)
    assert len(edits.errors) == 3 and edits.changes == []


def test_content_notes_read_from_rows():
    rows = [{RS.C_ID: "post-03", RS.C_NOTE: "più breve"}, {RS.C_ID: "screen-07", RS.C_NOTE: "  "},
            {RS.C_ID: "Story-02", RS.C_NOTE: "togli l'emoji"}]
    assert RS.content_notes(rows) == {"post-03": "più breve", "story-02": "togli l'emoji"}
