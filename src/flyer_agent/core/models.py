"""Typed data contracts shared by every stage. Pure: no I/O."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ProductType = Literal[
    "farmaco", "integratore", "dispositivo_medico", "cosmetico", "igiene", "infanzia", "veterinario", "altro"
]


class Price(BaseModel):
    current_eur: Decimal
    previous_eur: Decimal | None = None
    discount_pct: int | None = None


class Product(BaseModel):
    id: str = Field(description="slug of name + format, unique in the flyer")
    name: str
    brand: str | None = None
    format: str | None = None
    description: str | None = Field(None, description="flyer's own descriptive line, verbatim")
    flyer_category: str = Field(description="category band as printed, e.g. 'Rimedi stagionali'")
    product_type: ProductType
    is_medicine: bool = Field(description="True if the medicine symbol is on the card")
    my_agora_only: bool = False
    private_label: bool = False
    hero: bool = Field(False, description="'Gli imperdibili' / cover product")
    price: Price
    price_group: str | None = Field(None, description="same id for products sharing one price card")
    page: int
    bbox: list[float] | None = Field(None, description="optional [x0,y0,x1,y1] 0-1 on the page, for image crops")
    needs_review: bool = False
    review_notes: list[str] = Field(default_factory=list)


class PromoTier(BaseModel):
    qty: int | None = None
    value: str  # "-20%", "-5€"


class Promotion(BaseModel):
    id: str
    kind: Literal["line_discount", "quantity_tier", "category_discount", "brand_panel", "up_to"]
    title: str
    scope: str
    tiers: list[PromoTier]
    page: int


class ServiceOffer(BaseModel):
    id: str
    title: str
    items: list[str] = Field(default_factory=list)
    price_eur: Decimal | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    booking: str | None = None
    page: int


class LoyaltyOffer(BaseModel):
    program: str = "My Agorà"
    reward_eur: Decimal
    every_eur: Decimal
    exclusions: list[str] = Field(default_factory=list)
    call_to_action: str | None = None


class FlyerTheme(BaseModel):
    headline: str
    script_word: str | None = None
    accent_hex: str | None = None  # sampled by code from the cover
    cover_image_ref: str | None = None


class FlyerData(BaseModel):
    flyer_id: str = ""
    title: str
    valid_from: date
    valid_to: date
    store_name: str | None = None
    theme: FlyerTheme
    products: list[Product]
    promotions: list[Promotion] = Field(default_factory=list)
    services: list[ServiceOffer] = Field(default_factory=list)
    loyalty: LoyaltyOffer | None = None
    app_promo: bool = False
    legal_footer: list[str] = Field(default_factory=list)
    source_pages: int = 0

    def product(self, pid: str) -> Product | None:
        return next((p for p in self.products if p.id == pid), None)

    def service(self, sid: str) -> ServiceOffer | None:
        return next((s for s in self.services if s.id == sid), None)

    def promotion(self, pid: str) -> Promotion | None:
        return next((p for p in self.promotions if p.id == pid), None)


# ---------- planning + content ----------

Topic = Literal["flyer_teaser", "product", "promotion", "service", "loyalty", "app", "last_call"]


class PostSpec(BaseModel):
    """What to write: decided by code (planning), handed to the LLM."""

    id: str
    kind: Literal["post", "story"]
    topic: Topic
    product_ids: list[str] = Field(default_factory=list)
    ref_ids: list[str] = Field(default_factory=list)
    publish_date: date
    brief: str


class PostCopy(BaseModel):
    """What the LLM writes for one PostSpec. Prices/dates only as placeholders."""

    id: str
    caption: str
    image_headline: str = Field(max_length=60)
    image_subline: str | None = None
    hashtags: list[str] = Field(default_factory=list)


class SocialCopyBatch(BaseModel):
    posts: list[PostCopy]


class ScreenSpec(BaseModel):
    id: str
    product_id: str


class ScreenCopy(BaseModel):
    id: str
    headline: str = Field(max_length=40)


class ScreenCopyBatch(BaseModel):
    screens: list[ScreenCopy]


class SocialPost(BaseModel):
    spec: PostSpec
    copy_: PostCopy = Field(alias="copy")
    caption_final: str = ""  # placeholders filled + disclaimers added (by code)
    disclaimers: list[str] = Field(default_factory=list)
    image_path: str | None = None

    model_config = {"populate_by_name": True}


class ScreenSlide(BaseModel):
    spec: ScreenSpec
    headline: str
    price_text: str
    old_price_text: str | None
    discount_text: str | None
    validity_text: str
    badge: str | None = None
    disclaimer: str | None = None
    image_path: str | None = None


class Issue(BaseModel):
    severity: Literal["blocking", "warning", "review"]
    target: str
    rule: str
    message: str


class ComplianceReport(BaseModel):
    issues: list[Issue] = Field(default_factory=list)

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "blocking"]


class ContentPack(BaseModel):
    flyer_id: str
    posts: list[SocialPost]
    screens: list[ScreenSlide]
    compliance: ComplianceReport = Field(default_factory=ComplianceReport)


# ---------- run manifest ----------

State = Literal[
    "INGESTED", "EXTRACTED", "DATA_APPROVED", "GENERATED", "CHECKED", "RENDERED", "PACK_APPROVED", "EXPORTED"
]


class Approval(BaseModel):
    gate: Literal["data", "pack"]
    by: str
    at: datetime
    note: str = ""


class LLMCallRecord(BaseModel):
    task: str
    provider: str
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_eur: float = 0.0
    latency_s: float = 0.0
    at: datetime


class Manifest(BaseModel):
    flyer_id: str
    source_name: str
    state: State
    created_at: datetime
    updated_at: datetime
    approvals: list[Approval] = Field(default_factory=list)
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)

    @property
    def cost_eur(self) -> float:
        return round(sum(c.cost_eur for c in self.llm_calls), 4)
