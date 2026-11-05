from datetime import date
from decimal import Decimal

import pytest

from flyer_agent.core import planning, state
from flyer_agent.core.models import FlyerData
from flyer_agent.core.placeholders import PlaceholderError, eur, fill, find_literals
from flyer_agent.core.validation import expected_discount, validate


@pytest.mark.parametrize("prev,cur,printed", [
    ("16.90", "9.99", 40),   # 40.9% printed 40 (floor, not round)
    ("19.49", "16.59", 14),
    ("32.90", "24.49", 25),
    ("21.29", "18.09", 15),
])
def test_discount_is_rounded_down(prev, cur, printed):
    assert expected_discount(Decimal(prev), Decimal(cur)) == printed


def test_golden_flyer_validates_clean(golden: FlyerData):
    issues = validate(golden)
    assert [i for i in issues if i.severity in ("blocking", "warning")] == []
    assert len(golden.products) == 51


def test_wrong_price_is_blocking(golden: FlyerData):
    bad = golden.model_copy(deep=True)
    bad.products[0].price.current_eur = Decimal("21.79")
    assert any(i.rule == "discount_mismatch" for i in validate(bad))


def test_shared_price_group_must_match(golden: FlyerData):
    bad = golden.model_copy(deep=True)
    p = next(p for p in bad.products if p.price_group == "bisolvon")
    p.price.current_eur = Decimal("11.00")
    assert any(i.rule == "shared_price" for i in validate(bad))


def test_medicine_flag_consistency(golden: FlyerData):
    bad = golden.model_copy(deep=True)
    p = next(p for p in bad.products if p.product_type == "farmaco")
    p.is_medicine = False
    assert any(i.rule == "medicine_flag" and i.severity == "blocking" for i in validate(bad))


BRANDS = ["Enterogermina", "Benagol", "Nurofen"]


def test_known_medicine_brand_typed_as_supplement_is_blocking(golden: FlyerData):
    assert not [i for i in validate(golden, medicine_brands=BRANDS) if i.rule == "medicine_brand"]
    bad = golden.model_copy(deep=True)
    p = next(p for p in bad.products if p.name.startswith("Enterogermina"))
    p.product_type, p.is_medicine = "integratore", False
    issues = [i for i in validate(bad, medicine_brands=BRANDS) if i.rule == "medicine_brand"]
    assert len(issues) == 1 and issues[0].severity == "blocking"


def test_medicine_brand_prefix_and_exception(golden: FlyerData):
    bad = golden.model_copy(deep=True)
    p = next(p for p in bad.products if p.name == "NurofenXS")
    p.product_type, p.is_medicine = "altro", False
    assert any(i.rule == "medicine_brand" for i in validate(bad, medicine_brands=BRANDS))
    assert not any(i.rule == "medicine_brand"
                   for i in validate(bad, medicine_brands=BRANDS, not_medicine_exceptions=["^NurofenXS$"]))


def _symbols_of(data: FlyerData) -> list[tuple[int, str]]:
    return [(p.page, f"{p.price.current_eur:.2f}".replace(".", ",")) for p in data.products if p.is_medicine]


def test_medicine_symbols_match_golden(golden: FlyerData):
    issues = validate(golden, medicine_symbols=_symbols_of(golden))
    assert not [i for i in issues if i.rule.startswith("medicine_")]


def test_symbol_on_non_medicine_card_is_blocking(golden: FlyerData):
    syms = _symbols_of(golden)
    bad = golden.model_copy(deep=True)
    p = next(p for p in bad.products if p.name == "Momentact")
    p.product_type, p.is_medicine = "altro", False
    issues = validate(bad, medicine_symbols=syms)
    assert any(i.rule == "medicine_symbol" and i.severity == "blocking" and i.target == f"product:{p.id}"
               for i in issues)


def test_medicine_without_symbol_needs_review(golden: FlyerData):
    syms = _symbols_of(golden)
    bad = golden.model_copy(deep=True)
    p = next(p for p in bad.products if p.name.startswith("Swisse"))
    p.product_type, p.is_medicine = "farmaco", True
    issues = validate(bad, medicine_symbols=syms)
    assert any(i.rule == "medicine_no_symbol" and i.severity == "review" for i in issues)


def test_no_symbols_found_is_a_warning(golden: FlyerData):
    assert any(i.rule == "medicine_symbols_none" for i in validate(golden, medicine_symbols=[]))


def test_golden_scores_perfect_against_itself(golden: FlyerData):
    from flyer_agent.core.scoring import score_extraction
    s = score_extraction(golden, golden)
    assert s.core_pct == 100 and s.passed and not s.missing and not s.extra


def test_scoring_catches_price_and_medicine_errors(golden: FlyerData):
    from flyer_agent.core.scoring import score_extraction
    bad = golden.model_copy(deep=True)
    bad.products[0].price.current_eur = Decimal("1.00")
    med = next(p for p in bad.products if p.is_medicine and p is not bad.products[0])
    med.is_medicine = False
    bad.products.pop()
    s = score_extraction(bad, golden)
    assert len(s.price_errors) == 1 and len(s.medicine_errors) == 1 and len(s.missing) == 1
    assert not s.passed


def test_page_chunks():
    from flyer_agent.core.merge import page_chunks
    assert page_chunks(8, 3) == [[1, 2, 3], [4, 5, 6], [7, 8]]
    assert page_chunks(2, 3) == [[1, 2]]


def test_merge_parts_dedupes_and_keeps_cover_header(golden: FlyerData):
    from flyer_agent.core.merge import merge_parts
    a, b = golden.model_copy(deep=True), golden.model_copy(deep=True)
    b.title, b.loyalty = "titolo sbagliato", None
    merged = merge_parts([a, b])
    assert merged.title == golden.title and len(merged.products) == len(golden.products)
    assert merged.loyalty == golden.loyalty


def test_placeholders_are_filled_by_code(golden: FlyerData):
    pid = "enterogermina-4-miliardi-20-flaconcini-da-5-ml"
    out = fill(f"{{price:{pid}}} invece di {{old_price:{pid}}} ({{discount:{pid}}}) fino al {{valid_to}}", golden)
    assert out == "€19,79 invece di €28,29 (-30%) fino al 15 novembre"
    assert fill("{loyalty}", golden) == "€3 in regalo ogni €30 di spesa"
    assert fill("{service_price:cuore-in-movimento} fino al {service_valid_to:cuore-in-movimento}", golden) \
        == "€29 fino al 31 ottobre"
    with pytest.raises(PlaceholderError):
        fill("{price:does-not-exist}", golden)


def test_literal_numbers_detected():
    assert find_literals("a soli €19,79") and find_literals("sconto del 30%") and find_literals("fino al 15 novembre")
    assert not find_literals("fino al {valid_to} a {price:x}") and not find_literals("24 pastiglie")
    assert eur(Decimal("1234.5")) == "€1.234,50"


def test_planning(golden: FlyerData):
    specs = planning.plan_posts(golden, posts_max=12, stories_max=6, last_call_days=3)
    posts = [s for s in specs if s.kind == "post"]
    assert posts[0].topic == "flyer_teaser" and posts[0].publish_date == golden.valid_from
    assert len(posts) == 12 and posts[-1].topic == "last_call"
    assert all(golden.valid_from <= s.publish_date <= golden.valid_to for s in specs)
    svc = next(s for s in posts if s.ref_ids == ["cuore-in-movimento"])
    assert svc.publish_date < date(2026, 10, 31)
    # no two posts for products sharing one price card
    groups = [golden.product(s.product_ids[0]).price_group for s in posts if s.product_ids]
    assert len([g for g in groups if g]) == len({g for g in groups if g})
    assert len(planning.plan_screens(golden, 12)) == 12


def test_state_machine():
    assert state.can_run("generate", "DATA_APPROVED") and not state.can_run("generate", "EXTRACTED")
    with pytest.raises(state.StateError):
        state.next_state("export", "RENDERED")
