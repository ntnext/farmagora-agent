"""Decide WHAT to publish and WHEN. Deterministic, so the LLM only writes copy. Pure."""

from __future__ import annotations

from datetime import date, timedelta

from .models import FlyerData, PostSpec, Product, ScreenSpec


def _rank(products: list[Product]) -> list[Product]:
    # best discount first; non-medicines first (medicine posts always need manual review)
    return sorted(products, key=lambda p: (p.is_medicine, -(p.price.discount_pct or 0), p.page))


def _dedupe_groups(products: list[Product]) -> list[Product]:
    out, groups = [], set()
    for p in products:
        if p.price_group and p.price_group in groups:
            continue
        if p.price_group:
            groups.add(p.price_group)
        out.append(p)
    return out


def plan_posts(data: FlyerData, posts_max: int = 12, stories_max: int = 6,
               last_call_days: int = 3) -> list[PostSpec]:
    start, end = data.valid_from, data.valid_to
    days = max((end - start).days, 1)
    specs: list[PostSpec] = []

    def at(frac: float) -> date:
        return start + timedelta(days=round(days * frac))

    specs.append(PostSpec(id="post-01", kind="post", topic="flyer_teaser", publish_date=start,
                          brief="Annuncia il nuovo volantino e invita a sfogliarlo online o in farmacia."))

    heroes = _dedupe_groups([p for p in data.products if p.hero])
    for i, p in enumerate(heroes):
        specs.append(PostSpec(id="", kind="post", topic="product", product_ids=[p.id],
                              publish_date=at(0.05 + 0.08 * (i + 1)),
                              brief=f"Prodotto imperdibile del volantino: {p.name}."))

    for i, svc in enumerate(data.services):
        deadline = svc.valid_to or end
        when = min(at(0.12 + 0.2 * i), deadline - timedelta(days=5))
        when = max(when, start + timedelta(days=1))
        specs.append(PostSpec(id="", kind="post", topic="service", ref_ids=[svc.id], publish_date=when,
                              brief=f"Servizio in farmacia: {svc.title}."))

    for i, pr in enumerate(data.promotions):
        specs.append(PostSpec(id="", kind="post", topic="promotion", ref_ids=[pr.id],
                              publish_date=at(0.35 + 0.1 * i), brief=f"Promozione: {pr.title} ({pr.scope})."))

    if data.loyalty:
        specs.append(PostSpec(id="", kind="post", topic="loyalty", publish_date=at(0.5),
                              brief="Ricorda il vantaggio della carta My Agorà e invita a richiederla."))
    if data.app_promo:
        specs.append(PostSpec(id="", kind="post", topic="app", publish_date=at(0.6),
                              brief="Invita a scaricare l'app Farmagorà."))

    used = {pid for s in specs for pid in s.product_ids}
    used_groups = {data.product(pid).price_group for pid in used if data.product(pid)}  # type: ignore[union-attr]
    extra = [p for p in _rank(_dedupe_groups(data.products))
             if p.id not in used and (not p.price_group or p.price_group not in used_groups)]
    slots = posts_max - len(specs) - 1  # keep one for last call
    for i, p in enumerate(extra[:max(slots, 0)]):
        specs.append(PostSpec(id="", kind="post", topic="product", product_ids=[p.id],
                              publish_date=at(0.3 + 0.55 * (i + 1) / (slots + 1)),
                              brief=f"Offerta del volantino: {p.name}."))

    specs.append(PostSpec(id="", kind="post", topic="last_call",
                          publish_date=max(end - timedelta(days=last_call_days), start),
                          brief="Ultimi giorni per approfittare delle offerte del volantino."))

    # stories: teaser + top discounts + last call
    top = _rank(_dedupe_groups(data.products))[: max(stories_max - 2, 0)]
    stories = [PostSpec(id="", kind="story", topic="flyer_teaser", publish_date=start,
                        brief="Story: è uscito il nuovo volantino.")]
    for i, p in enumerate(top):
        stories.append(PostSpec(id="", kind="story", topic="product", product_ids=[p.id],
                                publish_date=at(0.15 + 0.6 * i / max(len(top), 1)),
                                brief=f"Story offerta: {p.name}."))
    stories.append(PostSpec(id="", kind="story", topic="last_call",
                            publish_date=max(end - timedelta(days=1), start),
                            brief="Story: ultimo giorno delle offerte."))

    posts = sorted(specs, key=lambda s: (s.publish_date, s.topic != "flyer_teaser"))
    for i, s in enumerate(posts, 1):
        s.id = f"post-{i:02d}"
    stories.sort(key=lambda s: s.publish_date)
    for i, s in enumerate(stories, 1):
        s.id = f"story-{i:02d}"
    return posts + stories


def plan_screens(data: FlyerData, max_slides: int = 12) -> list[ScreenSpec]:
    heroes = [p for p in data.products if p.hero]
    rest = [p for p in _rank(_dedupe_groups(data.products)) if not p.hero]
    chosen = _dedupe_groups(heroes + rest)[:max_slides]
    return [ScreenSpec(id=f"screen-{i:02d}", product_id=p.id) for i, p in enumerate(chosen, 1)]
