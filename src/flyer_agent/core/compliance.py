"""Compliance rules on the generated content. Pure: rules come in as a dict from compliance.yaml."""

from __future__ import annotations

import re
from typing import Any

from .models import ComplianceReport, ContentPack, FlyerData, Issue, SocialPost
from .placeholders import PlaceholderError, fill, find_literals

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def disclaimers_for(post: SocialPost, data: FlyerData, rules: dict[str, Any]) -> list[str]:
    """Mandatory small print for a post, added by code (never by the LLM)."""
    out: list[str] = []
    products = [p for pid in post.spec.product_ids if (p := data.product(pid)) is not None]
    if any(p.my_agora_only for p in products):
        out.append(rules["loyalty"]["label_card_only_prices"])
    if any(p.is_medicine for p in products):
        out.append(rules["medicines"]["mandatory_warning"])
    if post.spec.topic in {"product", "promotion", "last_call", "flyer_teaser"}:
        footer = data.legal_footer or rules["legal_footer_default"]
        out.append(footer[0])
    if post.spec.topic == "loyalty" and data.loyalty and data.loyalty.exclusions:
        out.append("Esclusi: " + ", ".join(data.loyalty.exclusions) + ".")
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def check(pack: ContentPack, data: FlyerData, rules: dict[str, Any], channels: dict[str, Any]) -> ComplianceReport:
    issues: list[Issue] = []
    forbidden = [re.compile(p, re.IGNORECASE) for p in rules["claims"]["forbidden_patterns"]]
    cap_max = channels["social"]["caption_max_chars"]
    tags_max = channels["social"]["hashtags_max"]

    def add(sev: str, target: str, rule: str, msg: str) -> None:
        issues.append(Issue(severity=sev, target=target, rule=rule, message=msg))  # type: ignore[arg-type]

    for post in pack.posts:
        t, c, s = post.spec.id, post.copy_, post.spec
        llm_text = " ".join([c.caption, c.image_headline, c.image_subline or ""])
        for pat in forbidden:
            if pat.search(llm_text):
                add("blocking", t, "forbidden_claim", f"forbidden wording: /{pat.pattern}/")
        lits = find_literals(llm_text)
        if lits and not rules["prices_and_dates"]["llm_may_write_literals"]:
            add("blocking", t, "literal_numbers", "LLM wrote prices/dates/percentages directly: " + ", ".join(lits))
        try:
            fill(llm_text, data)
        except PlaceholderError as e:
            add("blocking", t, "placeholder", str(e))
        if len(c.caption) > cap_max:
            add("warning", t, "caption_length", f"caption {len(c.caption)} > {cap_max} chars")
        if len(c.hashtags) > tags_max:
            add("warning", t, "hashtags", f"{len(c.hashtags)} hashtags > {tags_max}")
        if len(EMOJI_RE.findall(c.caption)) > 1:
            add("warning", t, "emoji", "more than one emoji")
        for pid in s.product_ids:
            p = data.product(pid)
            if not p:
                add("blocking", t, "unknown_ref", f"unknown product {pid}")
            elif p.is_medicine and rules["medicines"]["manual_review"]:
                add("review", t, "medicine", f"{p.name} is a medicine: check the copy manually")
        for rid in s.ref_ids:
            if not (data.service(rid) or data.promotion(rid)):
                add("blocking", t, "unknown_ref", f"unknown service/promotion {rid}")
            sv = data.service(rid)
            if sv and sv.valid_to and s.publish_date > sv.valid_to:
                add("blocking", t, "service_after_deadline", "service promoted after its end date")
        if not (data.valid_from <= s.publish_date <= data.valid_to):
            add("blocking", t, "publish_window", "publish date outside the flyer validity")
        if s.topic == "loyalty" and data.loyalty and not data.loyalty.exclusions:
            add("review", t, "loyalty_exclusions", "loyalty exclusions unknown for this flyer: confirm small print")
        if s.kind == "story" and any((data.product(pid) or None) and data.product(pid).is_medicine  # type: ignore[union-attr]
                                     for pid in s.product_ids) and "stories" in rules["medicines"].get("forbid_in", []):
            add("blocking", t, "medicine_story", "medicines not allowed in stories")

    for sc in pack.screens:
        p = data.product(sc.spec.product_id)
        for pat in forbidden:
            if pat.search(sc.headline):
                add("blocking", sc.spec.id, "forbidden_claim", f"forbidden wording: /{pat.pattern}/")
        if find_literals(sc.headline):
            add("blocking", sc.spec.id, "literal_numbers", "LLM wrote numbers in the headline")
        if p and p.is_medicine and rules["medicines"]["manual_review"]:
            add("review", sc.spec.id, "medicine", f"{p.name} is a medicine: check the slide manually")
    return ComplianceReport(issues=issues)
