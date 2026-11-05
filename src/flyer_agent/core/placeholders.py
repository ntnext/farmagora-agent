"""Prices, discounts and dates are written by code, never by the LLM. Pure."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from .models import FlyerData

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre"]

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)(?::([a-z0-9\-]+))?\}")
# literal prices / percentages / day-month dates that the LLM must not write itself
LITERAL_RE = re.compile(
    r"(€\s?\d)|(\d+[,.]\d{2}\s?€)|(\b\d{1,2}\s?%)|(\b\d{1,2}\s+(?:" + "|".join(MONTHS) + r")\b)", re.IGNORECASE
)


def eur(v: Decimal) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€{s}"


def eur_short(v: Decimal) -> str:
    return eur(v)[:-3] if v == v.to_integral_value() else eur(v)


def day_month(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


class PlaceholderError(ValueError):
    pass


def fill(text: str, data: FlyerData) -> str:
    def rep(m: re.Match[str]) -> str:
        key, arg = m.group(1), m.group(2)
        if key == "valid_to":
            return day_month(data.valid_to)
        if key == "valid_from":
            return day_month(data.valid_from)
        if key == "website":
            return "www.farmagora.it"
        if key == "loyalty":
            if not data.loyalty:
                raise PlaceholderError("no loyalty offer in flyer")
            return f"{eur_short(data.loyalty.reward_eur)} in regalo ogni {eur_short(data.loyalty.every_eur)} di spesa"
        if key in {"price", "old_price", "discount"}:
            p = data.product(arg or "")
            if not p:
                raise PlaceholderError(f"unknown product '{arg}'")
            if key == "price":
                return eur(p.price.current_eur)
            if key == "old_price":
                if p.price.previous_eur is None:
                    raise PlaceholderError(f"no old price for '{arg}'")
                return eur(p.price.previous_eur)
            if p.price.discount_pct is None:
                raise PlaceholderError(f"no discount for '{arg}'")
            return f"-{p.price.discount_pct}%"
        if key == "promo":
            pr = data.promotion(arg or "")
            if not pr:
                raise PlaceholderError(f"unknown promotion '{arg}'")
            parts = [f"{t.value} acquistando {t.qty} prodott{'o' if t.qty == 1 else 'i'}" if t.qty else t.value
                     for t in pr.tiers]
            return ", ".join(parts)
        if key in {"service_price", "service_valid_to"}:
            s = data.service(arg or "")
            if not s:
                raise PlaceholderError(f"unknown service '{arg}'")
            if key == "service_price":
                if s.price_eur is None:
                    raise PlaceholderError(f"service '{arg}' has no price")
                return eur_short(s.price_eur)
            return day_month(s.valid_to or data.valid_to)
        raise PlaceholderError(f"unknown placeholder '{m.group(0)}'")

    return PLACEHOLDER_RE.sub(rep, text)


def find_literals(text: str) -> list[str]:
    """Literal prices/percentages/dates in LLM text (placeholders removed first)."""
    stripped = PLACEHOLDER_RE.sub("", text)
    return [m.group(0) for m in LITERAL_RE.finditer(stripped)]
