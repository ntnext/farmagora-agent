"""Score an extraction against a hand-checked golden FlyerData (PLAN.md §10, M1 criteria). Pure."""

from __future__ import annotations

import difflib
import re
import unicodedata
from decimal import Decimal

from pydantic import BaseModel, Field

from .models import FlyerData, Product

CORE_TARGET_PCT = 98.0  # M1: exact match on name + prices + badges
FIELDS = ("name", "prices", "badges", "is_medicine", "product_type", "page")


class ExtractionScore(BaseModel):
    products_golden: int
    products_got: int
    matched: int
    missing: list[str] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)
    core_exact: int = 0  # matched products with name + prices + badges all correct
    field_ok: dict[str, int] = Field(default_factory=dict)
    medicine_errors: list[str] = Field(default_factory=list)
    price_errors: list[str] = Field(default_factory=list)
    dates_ok: bool = False
    promotions: tuple[int, int] = (0, 0)  # (found, golden)
    services: tuple[int, int] = (0, 0)
    loyalty_ok: bool = True

    @property
    def core_pct(self) -> float:
        return round(100 * self.core_exact / max(self.products_golden, 1), 1)

    def pct(self, field: str) -> float:
        return round(100 * self.field_ok.get(field, 0) / max(self.matched, 1), 1)

    @property
    def passed(self) -> bool:
        """M1 bar: ≥98% core exact, all promotions/services/loyalty found, dates right, no medicine errors."""
        return (self.core_pct >= CORE_TARGET_PCT and self.dates_ok and self.loyalty_ok and not self.medicine_errors
                and self.promotions[0] == self.promotions[1] and self.services[0] == self.services[1])


def _norm(text: str | None) -> str:
    t = (text or "").replace("\u2019", "'").replace("\u2018", "'")  # typographic apostrophes
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _tokens(p: Product) -> frozenset[str]:
    """Name + format as a token set: tolerant to "Gusto Limone" sitting in the name or in the format."""
    return frozenset(_norm(f"{p.name} {p.format or ''}").split())


def _match(golden: list[Product], got: list[Product]) -> list[tuple[Product, Product]]:
    """Pair products: same id first, then closest name + format (greedy, cutoff 0.6)."""
    pairs: list[tuple[Product, Product]] = []
    left = list(got)
    by_id = {p.id: p for p in left}
    rest = []
    for g in golden:
        if g.id in by_id and by_id[g.id] in left:
            pairs.append((g, by_id[g.id]))
            left.remove(by_id[g.id])
        else:
            rest.append(g)
    for g in rest:
        keys = [" ".join(sorted(_tokens(p))) for p in left]
        hit = difflib.get_close_matches(" ".join(sorted(_tokens(g))), keys, n=1, cutoff=0.6)
        if hit:
            p = left[keys.index(hit[0])]
            pairs.append((g, p))
            left.remove(p)
    return pairs


def _prices(p: Product) -> tuple[Decimal, Decimal | None, int | None]:
    return p.price.current_eur, p.price.previous_eur, p.price.discount_pct


def _badges(p: Product) -> tuple[bool, bool, bool, bool]:
    return p.is_medicine, p.my_agora_only, p.private_label, p.hero


def score_extraction(got: FlyerData, golden: FlyerData) -> ExtractionScore:
    """Compare an extraction with the golden file field by field."""
    pairs = _match(golden.products, got.products)
    paired_g = {id(g) for g, _ in pairs}
    paired_p = {id(p) for _, p in pairs}
    s = ExtractionScore(products_golden=len(golden.products), products_got=len(got.products), matched=len(pairs),
                        missing=[g.name for g in golden.products if id(g) not in paired_g],
                        extra=[p.name for p in got.products if id(p) not in paired_p])
    ok = dict.fromkeys(FIELDS, 0)
    for g, p in pairs:
        checks = {
            "name": _tokens(g) == _tokens(p),
            "prices": _prices(g) == _prices(p),
            "badges": _badges(g) == _badges(p),
            "is_medicine": g.is_medicine == p.is_medicine,
            "product_type": g.product_type == p.product_type,
            "page": g.page == p.page,
        }
        for k, v in checks.items():
            ok[k] += v
        s.core_exact += checks["name"] and checks["prices"] and checks["badges"]
        if not checks["is_medicine"]:
            s.medicine_errors.append(f"{g.name}: golden {g.is_medicine}, got {p.is_medicine}")
        if not checks["prices"]:
            s.price_errors.append(f"{g.name}: golden {_prices(g)}, got {_prices(p)}")
    s.field_ok = ok
    s.dates_ok = (got.valid_from, got.valid_to) == (golden.valid_from, golden.valid_to)
    s.promotions = (_found([x.title for x in golden.promotions], [x.title for x in got.promotions],
                           [x.page for x in golden.promotions], [x.page for x in got.promotions]),
                    len(golden.promotions))
    s.services = (_found([x.title for x in golden.services], [x.title for x in got.services],
                         [x.page for x in golden.services], [x.page for x in got.services]), len(golden.services))
    if golden.loyalty:
        s.loyalty_ok = bool(got.loyalty) and (got.loyalty.reward_eur, got.loyalty.every_eur) == (  # type: ignore[union-attr]
            golden.loyalty.reward_eur, golden.loyalty.every_eur)
    return s


def _found(golden_titles: list[str], got_titles: list[str], golden_pages: list[int], got_pages: list[int]) -> int:
    """Count golden items found: same normalised title, or any item on the same page (titles get paraphrased)."""
    got_norm = [_norm(t) for t in got_titles]
    return sum(1 for t, pg in zip(golden_titles, golden_pages, strict=True)
               if _norm(t) in got_norm or pg in got_pages)
