"""Split a flyer into page batches for models with few images per request, and merge the partial results. Pure."""

from __future__ import annotations

from .models import FlyerData


def page_chunks(n_pages: int, max_per_call: int) -> list[list[int]]:
    """1-based page numbers in consecutive batches of at most `max_per_call` pages."""
    size = max(1, max_per_call)
    return [list(range(start, min(start + size, n_pages + 1))) for start in range(1, n_pages + 1, size)]


def merge_parts(parts: list[FlyerData]) -> FlyerData:
    """Merge per-batch extractions. Header fields (title, validity, theme) come from the batch with the cover.

    Products, promotions and services are concatenated in page order; duplicates (same id) keep the first.
    """
    if not parts:
        raise ValueError("no parts to merge")
    merged = parts[0].model_copy(deep=True)
    for attr in ("products", "promotions", "services"):
        seen: set[str] = set()
        items = []
        for part in parts:
            for item in getattr(part, attr):
                if item.id not in seen:
                    seen.add(item.id)
                    items.append(item.model_copy(deep=True))
        setattr(merged, attr, items)
    merged.loyalty = next((p.loyalty for p in parts if p.loyalty), None)
    merged.app_promo = any(p.app_promo for p in parts)
    merged.legal_footer = list(dict.fromkeys(line for p in parts for line in p.legal_footer))
    return merged
