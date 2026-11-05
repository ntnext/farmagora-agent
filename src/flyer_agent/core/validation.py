"""Deterministic checks on FlyerData (run after extraction and after manual edits). Pure."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from decimal import Decimal

from .models import FlyerData, Issue

PRICE_RE = re.compile(r"€\s?(\d{1,3}(?:\.\d{3})*,\d{2})")


def expected_discount(previous: Decimal, current: Decimal) -> int:
    """Farmagorà prints the discount rounded DOWN (e.g. 24.9% -> 24%)."""
    return math.floor((previous - current) / previous * 100 + Decimal("1e-9"))


def _brand_pattern(brands: Iterable[str]) -> re.Pattern[str] | None:
    """Match a product name that starts a word with one of the brands (prefix: "Nurofen" matches "NurofenXS")."""
    alts = [re.escape(b.strip()) for b in brands if b.strip()]
    return re.compile(r"(?<!\w)(" + "|".join(alts) + ")", re.IGNORECASE) if alts else None


def _eur_it(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}".replace(".", ",")


def _check_medicine_symbols(data: FlyerData, symbols: list[tuple[int, str]],
                            add: Callable[[str, str, str, str], None]) -> None:
    """Cross-check medicine flags against symbols found by code: (page, price printed on the same card)."""
    if not symbols:
        add("warning", "flyer", "medicine_symbols_none",
            "no medicine symbol found by code in the PDF: check every card by hand")
        return
    marked = set(symbols)
    for page, price in sorted(marked):
        on_card = [p for p in data.products if p.page == page
                   and price in (_eur_it(p.price.current_eur), _eur_it(p.price.previous_eur))]
        if not on_card:
            add("review", f"page:{page}", "medicine_symbol_unmatched",
                f"medicine symbol next to €{price} on page {page}, but no product with that price there")
        elif not any(p.is_medicine for p in on_card):
            for p in on_card:
                add("blocking", f"product:{p.id}", "medicine_symbol",
                    f"medicine symbol printed on this card (page {page}, €{price}) but product is "
                    f"{p.product_type} (is_medicine=False)")
    for p in data.products:
        if p.is_medicine and not ({(p.page, _eur_it(p.price.current_eur)), (p.page, _eur_it(p.price.previous_eur))}
                                  & marked):
            add("review", f"product:{p.id}", "medicine_no_symbol",
                "marked as medicine but no medicine symbol found next to its price: confirm on the card")


def validate(data: FlyerData, text_layer: str | None = None, medicine_brands: Iterable[str] = (),
             not_medicine_exceptions: Iterable[str] = (),
             medicine_symbols: list[tuple[int, str]] | None = None) -> list[Issue]:
    """Run deterministic checks.

    `medicine_brands` / `not_medicine_exceptions` come from compliance.yaml. `medicine_symbols` are
    (page, price) pairs found by code in the PDF; None skips that cross-check.
    """
    brand_re = _brand_pattern(medicine_brands)
    exceptions = [re.compile(x, re.IGNORECASE) for x in not_medicine_exceptions]
    issues: list[Issue] = []

    def add(sev: str, target: str, rule: str, msg: str) -> None:
        issues.append(Issue(severity=sev, target=target, rule=rule, message=msg))  # type: ignore[arg-type]

    if data.valid_to < data.valid_from:
        add("blocking", "flyer", "validity_order", "valid_to is before valid_from")
    if (data.valid_to - data.valid_from).days > 70:
        add("warning", "flyer", "validity_span", "validity longer than 70 days")

    seen: set[str] = set()
    groups: dict[str, set[tuple]] = defaultdict(set)
    for p in data.products:
        t = f"product:{p.id}"
        if p.id in seen:
            add("blocking", t, "duplicate_id", "duplicate product id")
        seen.add(p.id)
        pr = p.price
        if pr.current_eur <= 0:
            add("blocking", t, "price_positive", "current price must be > 0")
        if pr.previous_eur is not None:
            if pr.previous_eur <= pr.current_eur:
                add("blocking", t, "old_price_higher", "old price must be higher than current price")
            elif pr.discount_pct is not None:
                exp = expected_discount(pr.previous_eur, pr.current_eur)
                diff = abs(exp - pr.discount_pct)
                if diff == 1:
                    add("warning", t, "discount_rounding", f"printed {pr.discount_pct}% vs computed {exp}%")
                elif diff > 1:
                    add("blocking", t, "discount_mismatch", f"printed {pr.discount_pct}% vs computed {exp}%")
        if p.product_type == "farmaco" and not p.is_medicine:
            add("blocking", t, "medicine_flag", "product_type is farmaco but is_medicine is False")
        if brand_re and not (p.product_type == "farmaco" and p.is_medicine):
            m = brand_re.search(p.name)
            if m and not any(x.search(p.name) for x in exceptions):
                add("blocking", t, "medicine_brand",
                    f"'{m.group(1)}' is a known medicine brand but product is {p.product_type} "
                    f"(is_medicine={p.is_medicine}): check the medicine symbol on the card")
        if p.price_group:
            groups[p.price_group].add((pr.current_eur, pr.previous_eur, pr.discount_pct))
        if p.needs_review:
            add("review", t, "extractor_flag", "; ".join(p.review_notes) or "flagged by extractor")

    if medicine_symbols is not None:
        _check_medicine_symbols(data, medicine_symbols, add)

    for g, prices in groups.items():
        if len(prices) > 1:
            add("blocking", f"price_group:{g}", "shared_price", "products in the same price group have different prices")

    for s in data.services:
        t = f"service:{s.id}"
        if s.valid_from and s.valid_to and s.valid_from > s.valid_to:
            add("blocking", t, "validity_order", "service valid_from after valid_to")
        if s.valid_to and s.valid_to < data.valid_from:
            add("blocking", t, "validity_overlap", "service ends before the flyer starts")

    if data.loyalty and not data.loyalty.exclusions:
        add("review", "loyalty", "loyalty_exclusions", "no exclusions found on this flyer: confirm them")
    if not data.legal_footer:
        add("warning", "flyer", "legal_footer", "legal footer not extracted; default from compliance.yaml will be used")

    if text_layer:
        printed = {m.replace(".", "") for m in PRICE_RE.findall(text_layer)}
        known: set[str] = set()
        for p in data.products:
            known.add(f"{p.price.current_eur:.2f}".replace(".", ","))
            if p.price.previous_eur is not None:
                known.add(f"{p.price.previous_eur:.2f}".replace(".", ","))
        for s in data.services:
            if s.price_eur is not None:
                known.add(f"{s.price_eur:.2f}".replace(".", ","))
        missing = sorted(printed - known)
        if missing:
            add("review", "flyer", "text_layer_prices",
                "prices in the PDF text not found in the data: " + ", ".join("€" + m for m in missing))
    return issues
