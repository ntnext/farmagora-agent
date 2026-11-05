"""Offline provider: lets the whole pipeline run with NO API key.

- extract: replays the hand-checked golden file of a known fixture flyer (matched by SHA-256);
- copy tasks: rule-based Italian copy built from the planning context (placeholders only).
It implements the same LLMClient port, so it doubles as the fake used by tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from ...core.models import FlyerData, ScreenCopyBatch, SocialCopyBatch
from ...ports.llm import Capabilities, LLMError, Part, PdfPart, TextPart
from .base import BaseLLM

CONTEXT_TAG = "CONTEXT_JSON"

CATEGORY_EMOJI = {
    "Rimedi stagionali": "🍂", "Vitamine e integratori": "🍊", "Benessere gastrointestinale": "🌿",
    "Dolore": "💪", "Salute e benessere": "🌙", "Bambino": "👶", "Bellezza del corpo e del viso": "✨",
    "Igiene personale": "🫧", "Gli imperdibili": "⭐",
}


def _context(inputs: list[Part]) -> dict:
    for p in inputs:
        if isinstance(p, TextPart) and p.text.startswith(CONTEXT_TAG):
            return json.loads(p.text[len(CONTEXT_TAG):])
    raise LLMError("offline provider needs the planning context")


class OfflineLLM(BaseLLM):
    provider = "offline"

    def __init__(self, model: str = "rules-v1", fixtures_dir: str = "tests/fixtures/flyers", **_):
        super().__init__(model, Capabilities(pdf_input=True, image_input=True, json_schema=True))
        self.fixtures_dir = Path(fixtures_dir)

    # -- extraction: replay golden data
    def _golden_for(self, pdf: Path) -> Path:
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        for f in sorted(self.fixtures_dir.glob("*.pdf")):
            if hashlib.sha256(f.read_bytes()).hexdigest() == digest:
                g = f.with_suffix(".golden.json")
                if g.exists():
                    return g
        raise LLMError("offline provider has no recorded data for this flyer: "
                       "set a real provider for the 'extract' task in config/app.yaml")

    def _call(self, system: str, prompt: str, inputs: list[Part], schema: type[BaseModel],
              temperature: float) -> tuple[str, int, int]:
        if schema is FlyerData:
            pdf = next(p for p in inputs if isinstance(p, PdfPart))
            return self._golden_for(pdf.path).read_text(encoding="utf-8"), 0, 0
        ctx = _context(inputs)
        if schema is SocialCopyBatch:
            return json.dumps({"posts": [self._post(s, ctx) for s in ctx["posts"]]}, ensure_ascii=False), 0, 0
        if schema is ScreenCopyBatch:
            return json.dumps({"screens": [self._screen(s, ctx) for s in ctx["screens"]]}, ensure_ascii=False), 0, 0
        raise LLMError(f"offline provider cannot produce {schema.__name__}")

    # -- rule-based copy (Italian, Farmagorà tone, placeholders only)
    def _post(self, spec: dict, ctx: dict) -> dict:
        topic, story = spec["topic"], spec["kind"] == "story"
        sid = spec["id"]
        if topic == "flyer_teaser":
            cap = ("📖 Hai già visto il nostro nuovo volantino? Sfoglialo comodamente su {website} o direttamente "
                   "in farmacia e scopri le promozioni che abbiamo selezionato per te, valide fino al {valid_to}!")
            return {"id": sid, "caption": cap if not story else "📖 È uscito il nuovo volantino! Sfoglialo su {website}.",
                    "image_headline": "SFOGLIA IL", "image_subline": "volantino",
                    "hashtags": ["#Farmagorà", "#volantino"]}
        if topic == "product":
            p = ctx["products"][spec["product_ids"][0]]
            emoji = CATEGORY_EMOJI.get(p["flyer_category"], "💙")
            fmt = f" ({p['format']})" if p.get("format") else ""
            pid = p["id"]
            card = " con la carta My Agorà" if p["my_agora_only"] else ""
            if story:
                cap = f"{emoji} {p['name']}: {{discount:{pid}}}{card}, fino al {{valid_to}}."
            else:
                cap = (f"{emoji} In offerta questo mese da Farmagorà: {p['name']}{fmt} a {{price:{pid}}} "
                       f"invece di {{old_price:{pid}}}{card}. Ti aspettiamo in farmacia fino al {{valid_to}}: "
                       "chiedi consiglio al tuo farmacista!")
            return {"id": sid, "caption": cap, "image_headline": p["name"][:60], "image_subline": p.get("format"),
                    "hashtags": ["#Farmagorà", "#offerte"]}
        if topic == "service":
            s = ctx["services"][spec["ref_ids"][0]]
            items = ", ".join(s["items"][:4])
            price = f" a soli {{service_price:{s['id']}}}" if s.get("price_eur") else ""
            until = f" fino al {{service_valid_to:{s['id']}}}" if s.get("valid_to") else ""
            book = f" Prenota {s['booking']}." if s.get("booking") else " Chiedi informazioni in farmacia."
            what = f": {items}" if items else ""
            where = "" if "Farmagor" in s["title"] else " da Farmagorà"
            cap = f"❤️ {s['title']}{where}{what}{price}{until}.{book}"
            return {"id": sid, "caption": cap, "image_headline": s["title"][:60], "image_subline": None,
                    "hashtags": ["#Farmagorà", "#servizi"]}
        if topic == "promotion":
            pr = ctx["promotions"][spec["ref_ids"][0]]
            cap = f"🐾 {pr['title']}! {{promo:{pr['id']}}} su {pr['scope']}. Ti aspettiamo in farmacia!"
            return {"id": sid, "caption": cap, "image_headline": pr["title"][:60], "image_subline": pr["scope"][:80],
                    "hashtags": ["#Farmagorà"]}
        if topic == "loyalty":
            cap = ("💳 Lo sapevi? Con la carta My Agorà hai {loyalty}. "
                   "Richiedila in farmacia o su {website}!")
            return {"id": sid, "caption": cap, "image_headline": "Carta My Agorà", "image_subline": "Richiedila in farmacia o sul nostro sito",
                    "hashtags": ["#Farmagorà", "#MyAgorà"]}
        if topic == "app":
            return {"id": sid, "caption": "📱 Hai già la nostra app? Scaricala e scopri tutti i vantaggi!",
                    "image_headline": "Scarica l'app", "image_subline": None, "hashtags": ["#Farmagorà"]}
        if topic == "last_call":
            cap = ("⏰ Ultimi giorni! Le offerte del volantino sono valide fino al {valid_to}: "
                   "passa in farmacia o sfoglialo su {website}.")
            if story:
                cap = "⏰ Ultimo giorno per le offerte del volantino!"
            return {"id": sid, "caption": cap, "image_headline": "ULTIMI GIORNI", "image_subline": "fino al {valid_to}",
                    "hashtags": ["#Farmagorà"]}
        raise LLMError(f"unknown topic {topic}")

    def _screen(self, spec: dict, ctx: dict) -> dict:
        p = ctx["products"][spec["product_id"]]
        headline = "Gli imperdibili" if p["hero"] else f"{p['flyer_category']}"
        return {"id": spec["id"], "headline": headline[:40]}
