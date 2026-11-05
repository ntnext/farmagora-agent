# Farmagorà — Flyer-to-Everything Agent

Build plan and technical spec. Hand this file (plus `CLAUDE.md`) to Claude Code and build milestone by milestone.

## 0. Status (v0.1, 3 Nov 2026)

Built and running (`README.md`): M0, M0.5 (adapter layer for Anthropic, OpenAI, Gemini, OpenAI-compatible + offline), M2, M3, M4, M5 on the Oct–Nov 2026 fixture with the offline provider; 24 tests green.

M1 in progress (4 Nov 2026), Gemini `gemini-3.5-flash` (free tier), prompt `extract_flyer.v3` + medicine symbols found by code (§7):
- Oct–Nov 2026 vs golden: 51/51 products, 100% prices/discounts/dates/badges, 51/51 medicine flags, names 94% (apostrophe style, flavour in name vs format), product type 90% (cosmetico vs infanzia/altro, not safety-relevant).
- May 2026 (44 products) and Jul–Aug 2025 (36 products): 0 blocking issues, every PDF price matched; v2 had 7 medicine errors (symbol given to the neighbouring card), all fixed by v3. Drafts saved as `tests/fixtures/flyers/*.golden.draft.json`: **to be hand-checked**, then renamed to `*.golden.json`.
- Free-tier Pro models have no quota and Flash models often return 503 "high demand": a paid key is needed for reliable runs.

M6 in progress (4 Nov 2026):
- Done: cost tracking (`config/pricing.yaml`, Gemini thinking tokens counted), automatic retry of 5xx errors (10/30/60 s), AI copy on Gemini (`copy_social.v2`: no format/strength in captions), `flyer score` and `flyer eval --providers`, product photos found by code (`photos.json`, 34/36 on Jul–Aug), template fixes, `DEMO.md` script.
- First full Gemini run (Jul–Aug 2025, run `dd687935ddfa`): ~2.7 min machine time without retry waits (extract 108 s, copy 48 s, render 5 s), **€0.10 per flyer** (paid-tier prices), 30 images, 0 blocking compliance issues after one regen. Oct–Nov extraction scores 100% name + prices + badges (`flyer score`).
- Blocked: a clean one-shot run (free tier: 503 "high demand" and 20 requests/day per model), provider comparison (needs a second provider key), demo recording (owner).

M7a built (4 Nov 2026), Drive **desktop sync** variant of §14 (§14.0): `flyer watch`, approvals by renaming files, data fixes and change requests in `Revisione.xlsx` (Google Sheets in the browser), macOS notifications; tested end to end on a temporary folder with the offline provider. Default providers: Gemini for `extract`, Groq (`openai/gpt-oss-120b`) for copy (both free tiers).

Not done yet: hand-check of the two draft golden files and scoring against them (rest of M1), rest of M6, LLM compliance critic, provider eval command, M6, M7 (Drive + Sheet agent, §14).

## 1. Goal

Starting from the monthly Farmagorà product flyer (PDF), automatically produce a ready-to-approve content pack:

| Output | Format | Quantity |
| --- | --- | --- |
| Flyer teaser post | "Sfoglia il volantino" post: caption + image with flyer cover mockup (see §1b) | 1 per flyer, always first in the calendar |
| Social posts | Caption (IT) + rendered image 1080×1350 PNG + suggested publish date | 8–12 per flyer (product, promo, service and My Agorà posts) |
| Stories | Rendered image 1080×1920 PNG + short text | 4–6 per flyer |
| In-store screens | Rendered slides 1920×1080 PNG (+ optional MP4 loop) | 1 per featured product, max 12 |
| Publishing calendar | CSV compatible with our PED Social sheet | 1 per flyer |

Scope for v1: **one store**, **one approver** (the project owner), **no automatic publishing**, **no newsletter** (Farmagorà does not send one). Everything is exported to a folder for manual upload.

LLM-agnostic by design: every AI step can run on Claude, GPT, Gemini, Mistral or a local model by changing `config/app.yaml` (see §8).

Success criteria:
- From flyer PDF to approved pack in **≤ 30 minutes of human time** (today: several hours).
- **0 price or date errors** in approved outputs (enforced by validation + human gate).
- Every output passes the compliance checks in §7.

## 1a. Flyer anatomy (learned from the 3 fixture flyers)

Fixtures in `tests/fixtures/flyers/`:

| File | Validity | Theme | Pages |
| --- | --- | --- | --- |
| `2025-07_luglio-agosto_la-salute-che-conviene.pdf` | 1 Jul – 31 Aug 2025 | "La salute che conviene" (summer, yellow) | 5 (inner pages are 2-page spreads) |
| `2026-05_maggio_salute-e-risparmio.pdf` | 1 – 31 May 2026 | "Salute e Risparmio" (spring, green) | 8 |
| `2026-10_ottobre-novembre_tieni-alte-le-difese.pdf` | 1 Oct – 15 Nov 2026 | "Tieni alte le difese" (autumn, orange) | 8 |

All three have a text layer, so extraction can use text + layout; vision is still needed to pair names with prices (the text layer lists prices and names out of order).

Recurring structure the extractor must recognise:

- **Cover:** logo, validity line ("DALL'1 OTTOBRE AL 15 NOVEMBRE 2026"), seasonal headline (bold sans + script word), My Agorà card promo, sometimes 2–4 "Gli imperdibili" hero products or a category promo.
- **Inner pages "La Piazza della Salute":** product cards grouped under coloured category bands. Categories seen: Rimedi stagionali, Salute e benessere, Benessere gastrointestinale, Vitamine e integratori, Dolore, Bellezza del corpo e del viso, Igiene personale, Medicazione, Bambino, Gli imperdibili.
- **Product card:** category band, name, format/description line (sometimes with the manufacturer's claim, e.g. "per favorire il sonno"), discount badge, old price (struck), new price, and optional badges:
  - **medicine symbol** (round "farmaco" icon) → the product is a medicine;
  - **"Solo con My Agorà"** → price valid only for card holders;
  - **"Prodotto Farmagorà"** → private label.
- **Shared price cards:** two products can share one price (e.g. Bisolvon Pocket + Sciroppo; Aboca Neobianacid limone + menta). Same product can appear in two formats (Irilens 10 ml and 15 monodosi), so product ids must include the format.
- **Promo blocks that are not single products:**
  - brand/line discounts ("-20% acquistando un prodotto della linea detersione di CeraVe");
  - quantity tiers ("-20% acquistando 2 prodotti solari, -30% acquistando 3"; NaturaMix "1 prodotto -5€, 2 -15€, 3 -25€");
  - category promos ("Ci siamo anche noi": -30% or -10% on pet products; "Sconti fino al 50% su prodotti solari");
  - multi-product brand panels (CeraVe panel with 3 priced products).
- **Services:** priced health packages with their own validity, which can differ from the flyer's ("Cuore in salute" €35, 1 May – 30 Jun; "Cuore in movimento" €29 until 31 Oct), service lists (ECG, Holter, spirometry, blood tests, intolerance tests, swabs and vaccinations, ear piercing), flu vaccination with booking "sull'agenda online o in farmacia".
- **My Agorà loyalty:** cashback rule that changes over time (2025: €2 every €20; 2026: €3 every €30) with exclusions (all medicines, "latti 1", SSN-reimbursable products).
- **App promo:** "Hai già la nostra app?" with QR code.
- **Legal footer (reuse verbatim):** "Offerte valide fino a esaurimento scorte. I prezzi potrebbero subire variazioni nel caso di errori o omissioni di stampa. Le fotografie hanno valore puramente illustrativo." and "Per un corretto uso del farmaco leggere attentamente tutte le informazioni presenti nel libretto illustrativo."
- **Network, not a single store:** every flyer says "Trova la farmacia Farmagorà più vicina su www.farmagora.it". v1 treats the flyer as network-wide; `store_name` is optional.
- **Discount rounding rule:** the printed % is the computed discount **rounded down** (e.g. €19,49 → €16,59 = 14.9% printed as 14%; €17,29 → €12,99 = 24.9% printed 24%). Validation uses floor, not round.

## 1b. Brand and tone (from the fixtures and the 21 Oct 2026 Facebook post)

- **Fixed brand (from the official logo `assets/logo-farmagora-orizzontale.jpg`):** navy **#015176** (wordmark, top block of the mark, badges, frames), yellow **#FED061** (two blocks and the "+" of the mark, accents), white backgrounds. Light tints of the navy (e.g. #E6EEF2) are allowed for page backgrounds as in the flyers. Logo "F+ FARMAGORÀ" horizontal; needs clear space on white or light backgrounds. Prices in a large italic script-style numeral with smaller cents ("€19,79").
- **Seasonal theme:** each flyer has its own cover colour and illustration (yellow umbrellas, green dandelions, orange leaves). The renderer takes a `theme` (accent colour + cover image crop) per run, extracted from the cover.
- **Headline style:** uppercase bold sans + one handwritten script word ("SFOGLIA IL *volantino*", "SALUTE E *Risparmio*", "LA SALUTE CHE *conviene*").
- **Frame motif in social posts:** navy corner brackets top-left and bottom-right, logo centred at the bottom (`tests/fixtures/social/2026-10-21_facebook_sfoglia-il-volantino.png`).
- **Caption tone:** friendly, short, one emoji at the start, opens with a question, closes with a clear CTA to farmagora.it and to the pharmacy. Example (use as few-shot): "📖 Hai già visto il nostro volantino del mese? Sfoglialo comodamente su www.farmagora.it o direttamente in farmacia e scopri le promozioni e i prodotti che abbiamo selezionato per le tue esigenze quotidiane!"

## 2. Architecture principles

- **Pipeline of small, pure stages.** Each stage reads typed input from disk and writes typed output to disk. Any stage can be re-run alone.
- **Typed contracts everywhere.** All data between stages is a Pydantic model serialised to JSON. LLM output is always parsed into these models, never passed around as free text.
- **Ports and adapters.** Business logic depends on interfaces (`LLMClient`, `Storage`, `Renderer`, `Publisher`), never on vendors. v1 adapters: LLM providers (Anthropic, OpenAI, Google Gemini, OpenAI-compatible endpoints for Mistral/local models), local filesystem, Playwright renderer, "folder export" publisher. Drive and Meta can be added later without touching the core.
- **Human-in-the-loop gates.** Two explicit approval gates (data, then content). The pipeline cannot advance past a gate without an approval record.
- **Deterministic where possible, LLM only where needed.** Price math, date checks, layout and compliance word lists are code. The LLM extracts data and writes copy.
- **Idempotent runs.** A run is keyed by the flyer's SHA-256. Re-running a stage overwrites only that stage's outputs and records a new version.
- **Prompts are versioned files**, not strings in code. Each output records the prompt version and model used.
- **Config over code** for brand, tone and compliance rules (YAML), so a non-developer can change them.
- **Observability.** Structured JSON logs, token usage and cost per stage, and a run manifest that explains what happened.

## 3. Tech stack

| Concern | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12 | Mature PDF, imaging and LLM tooling |
| Package/env | `uv` + `pyproject.toml` | Fast, reproducible |
| CLI | Typer | Simple commands for each stage and gate |
| Data models | Pydantic v2 | Validation + JSON schema for the LLM |
| LLM | Provider-agnostic `LLMClient` port; adapters on the official SDKs: `anthropic`, `openai`, `google-genai`; OpenAI-compatible adapter for Mistral, Groq, Ollama/vLLM. Provider + model chosen per task in `config/app.yaml` | No vendor lock-in; compare quality and cost per task; switch in one line |
| PDF handling | pypdfium2 (`pypdfium2`, Apache-2.0/BSD) | Page renders, text layer with character positions, embedded images (medicine symbols) |
| Templates | Jinja2 | Social, story and screen HTML templates |
| Rendering images | Playwright (Chromium) screenshot of HTML templates | Pixel-exact, brand fonts, easy to edit by designers |
| Optional video | `ffmpeg` | Loop screen slides into MP4 |
| Config | YAML + `pydantic-settings`; secrets in `.env` | Editable, safe |
| Review UI | Static `review.html` generated per run (no server) | Zero infrastructure |
| Google Drive (M7b) | `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` (Apache-2.0), extra `[drive]` | The agent works on the Drive folder online (no Drive desktop app); OAuth as the folder owner, token in `.secrets/` |
| Review spreadsheet | `openpyxl` (`Revisione.xlsx`, MIT) | Drive opens `.xlsx` in Google Sheets and saves edits back to the same file: price fixes and change requests from the browser (§14.0) |
| Tests | `pytest`, `pytest-recording`/fixtures for LLM calls | Offline, repeatable |
| Lint/format/type | `ruff`, `mypy --strict` on `core/` | Quality gate |

## 4. Repository structure

```
farmagora-flyer-agent/
├── CLAUDE.md
├── PLAN.md
├── pyproject.toml
├── .env.example                 # API keys for the providers you use
├── config/
│   ├── brand.yaml               # colours, fonts, logo path, tone of voice, emoji policy
│   ├── compliance.yaml          # forbidden words/claims, mandatory disclaimers, category rules
│   ├── channels.yaml            # sizes, counts, caption limits, hashtags
│   └── app.yaml                 # provider + model per task, temperatures, paths, cost limits
├── prompts/
│   ├── extract_flyer.v1.md
│   ├── generate_social.v1.md
│   ├── generate_screens.v1.md
│   └── compliance_review.v1.md
├── templates/
│   ├── social/post.html.j2
│   ├── social/story.html.j2
│   └── screens/slide.html.j2
├── assets/                      # logo-farmagora-orizzontale.jpg, fonts, fallback images
├── src/flyer_agent/
│   ├── core/                    # pure domain: models, validators, services (no I/O)
│   │   ├── models.py
│   │   ├── validation.py
│   │   ├── compliance.py
│   │   ├── planning.py          # which products go where, calendar
│   │   └── pipeline.py          # stage orchestration + state machine
│   ├── ports/                   # interfaces (typing.Protocol)
│   │   ├── llm.py
│   │   ├── storage.py
│   │   ├── renderer.py
│   │   └── publisher.py
│   ├── adapters/
│   │   ├── llm/
│   │   │   ├── base.py              # shared retry, JSON parsing, cost tracking
│   │   │   ├── anthropic_llm.py
│   │   │   ├── openai_llm.py
│   │   │   ├── gemini_llm.py
│   │   │   ├── openai_compatible_llm.py   # Mistral, Groq, Ollama, vLLM...
│   │   │   └── registry.py          # builds the client for a task from app.yaml
│   │   ├── local_storage.py
│   │   ├── pdf.py               # pypdfium2: renders, text layer, medicine symbols, crops
│   │   ├── playwright_renderer.py
│   │   └── folder_publisher.py
│   ├── stages/
│   │   ├── ingest.py
│   │   ├── extract.py
│   │   ├── generate.py
│   │   ├── render.py
│   │   └── export.py
│   ├── review/build_review_page.py
│   ├── observability.py         # logging, cost tracking
│   └── cli.py
├── runs/                        # one folder per run (gitignored)
└── tests/
    ├── fixtures/flyers/         # the 3 real flyers (PDF) + golden flyer_data JSON (created in M1, see §10)
    ├── fixtures/social/         # real published posts used as tone/visual references
    ├── unit/
    ├── integration/
    └── eval/                    # quality comparison vs past published outputs
```

Rule: `core/` imports nothing from `adapters/`, `stages/` or third-party I/O libraries. Stages wire ports to core.

## 5. Data contracts (core/models.py)

```python
class Price(BaseModel):
    current_eur: Decimal            # > 0, 2 decimals
    previous_eur: Decimal | None    # must be > current if present
    discount_pct: int | None        # printed %; must equal floor((prev-cur)/prev*100)

class Product(BaseModel):
    id: str                         # slug of name + format, stable within the run
    name: str                       # "Enterogermina 4 Miliardi"
    brand: str | None
    format: str | None              # "20 flaconcini da 5 ml"
    description: str | None         # flyer's own descriptive line, verbatim (may contain the manufacturer's claim)
    flyer_category: str             # category band as printed: "Rimedi stagionali", "Dolore", "Bambino"...
    product_type: Literal["farmaco", "integratore", "dispositivo_medico", "cosmetico",
                          "igiene", "infanzia", "veterinario", "altro"]
    is_medicine: bool               # True when the medicine symbol is on the card (or product_type == farmaco)
    my_agora_only: bool             # "Solo con My Agorà" badge
    private_label: bool             # "Prodotto Farmagorà" badge
    hero: bool                      # listed under "Gli imperdibili" / on the cover
    price: Price
    price_group: str | None         # same id for products sharing one price card
    page: int
    image_ref: str | None           # crop of the product image from the page render
    needs_review: bool              # set by validation or low LLM confidence
    review_notes: list[str]

class Promotion(BaseModel):        # offers that are not a single priced product
    id: str
    kind: Literal["line_discount", "quantity_tier", "category_discount", "brand_panel", "up_to"]
    title: str                      # "Goditi il primo sole", "Ci siamo anche noi"
    scope: str                      # "linea detersione CeraVe", "prodotti solari", "prodotti veterinari"
    tiers: list[PromoTier]          # e.g. [{qty:2, value:"-20%"}, {qty:3, value:"-30%"}] or [{qty:1, value:"-5€"}]
    page: int

class ServiceOffer(BaseModel):     # "Cuore in salute", flu vaccination, service list
    id: str
    title: str
    items: list[str]                # "Misurazione della pressione", "Pannello lipidico", ...
    price_eur: Decimal | None       # €35, €29
    valid_from: date | None         # may differ from the flyer validity
    valid_to: date | None
    booking: str | None             # "agenda online o in farmacia"
    page: int

class LoyaltyOffer(BaseModel):     # My Agorà card
    program: str = "My Agorà"
    reward_eur: Decimal             # 3
    every_eur: Decimal              # 30
    exclusions: list[str]           # "tutti i farmaci", "latti 1", "prodotti rimborsabili dal SSN"
    call_to_action: str             # "Richiedi la tua carta My Agorà in farmacia o sul nostro sito web."

class FlyerTheme(BaseModel):
    headline: str                   # "TIENI ALTE LE DIFESE"
    script_word: str | None         # "Risparmio", "conviene"
    accent_hex: str                 # dominant cover colour, sampled by code from the cover render
    cover_image_ref: str            # page-1 render, used for the teaser mockup

class FlyerData(BaseModel):
    flyer_id: str                   # sha256 of PDF
    title: str                      # e.g. "Tieni alte le difese"
    valid_from: date
    valid_to: date                  # >= valid_from
    store_name: str | None          # None = whole Farmagorà network
    theme: FlyerTheme
    products: list[Product]
    promotions: list[Promotion]
    services: list[ServiceOffer]
    loyalty: LoyaltyOffer | None
    app_promo: bool
    legal_footer: list[str]         # verbatim footer lines
    source_pages: int

class SocialPost(BaseModel):
    id: str
    kind: Literal["post", "story"]
    topic: Literal["flyer_teaser", "product", "promotion", "service", "loyalty", "app"]
    product_ids: list[str]          # must exist in FlyerData (empty for teaser/service/loyalty)
    ref_ids: list[str]              # promotion / service ids referenced
    caption: str                    # ≤ channels.yaml limit
    hashtags: list[str]
    image_headline: str             # ≤ 40 chars
    image_subline: str | None
    publish_date: date              # within validity window
    disclaimer: str | None          # injected by compliance, not by the LLM

class ScreenSlide(BaseModel):
    id: str
    product_id: str | None
    headline: str                   # ≤ 30 chars, readable from 3 m
    price_text: str                 # rendered from Price by code, never by LLM
    validity_text: str              # rendered by code
    duration_s: int = 8

class ContentPack(BaseModel):
    flyer_id: str
    posts: list[SocialPost]
    screens: list[ScreenSlide]
    calendar: list[CalendarEntry]
    compliance_report: ComplianceReport
```

Key rule: **prices, discounts and dates in final outputs are always formatted by code from `FlyerData`**, never copied from LLM text. The LLM writes copy with placeholders like `{price:product-id}` that the renderer fills.

## 6. Pipeline and state machine

```
INGESTED → EXTRACTED → DATA_APPROVED → GENERATED → CHECKED → RENDERED → PACK_APPROVED → EXPORTED
                 ↑ (edit + re-validate)          ↑ (regenerate item)
```

Run manifest `runs/<flyer_id>/manifest.json` stores: state, timestamps, stage versions, prompt versions, model, tokens, cost, approval records (who, when, notes).

| Stage | Input | Output | Notes |
| --- | --- | --- | --- |
| `ingest` | flyer PDF | `source.pdf`, `pages/*.png`, `text.json`, `symbols.json`, `photos.json` | Hash PDF, render pages, read the text layer, locate medicine symbols and product photos (paired with the card's price) with pypdfium2 |
| `extract` | PDF + page images | `flyer_data.json`, `validation.json` | One LLM call (task `extract`) with the PDF or page images + JSON schema; then deterministic validation (§7) |
| Gate 1 `approve-data` | `flyer_data.json` | approval record | Review in `review.html` (table of products with price, dates, flags). Edit the JSON, re-run `validate`, then approve |
| `generate` | approved `FlyerData` + config | `content_pack.json` (draft) | 2 calls (tasks `copy_social`, `copy_screens`). Planning is done by code first: teaser on day 1, heroes in week 1, services before their deadline (e.g. "Cuore in movimento" before 31 Oct), loyalty and app posts mid-period, last-call post 3 days before `valid_to`; then the LLM writes the copy |
| `check` | draft pack | `compliance_report.json` | Rules engine + LLM critic. Blocking issues stop the pipeline |
| `render` | checked pack + templates | `out/social/*.png`, `out/stories/*.png`, `out/screens/*.png`, `out/calendar.csv` | Playwright renders HTML templates at exact sizes |
| Gate 2 `approve-pack` | rendered outputs | approval record | Gallery in `review.html` with captions next to images; regenerate single items with `regen --item post-03 --note "..."` |
| `export` | approved pack | `export/<flyer_id>.zip` + folder | Folder publisher only in v1 |

## 7. Validation and compliance

Deterministic validation after extraction (blocks the gate if any fail):
- `valid_to ≥ valid_from`; validity spans ≤ 70 days.
- `current_eur > 0`; `previous_eur > current_eur`; printed discount == floor of the computed discount (checked on a sample of cards from all three fixtures; Lactoflorene €16,90 → €9,99 = 40.9% is printed 40%). Off by 1 point → warning; more → blocking.
- No duplicate products (id = name + format); every product has a page number; products with the same `price_group` share the same price.
- Service offers: own validity allowed, but `valid_from` must be ≤ `valid_to` and overlap the flyer window.
- `is_medicine` must be True for every card where the medicine symbol was detected; any `product_type == "farmaco"` with `is_medicine == False` is blocking.
- **Medicine symbols found by code** (`adapters/pdf.py: medicine_symbols`, saved as `symbols.json` at ingest): the round badge is a small embedded image; code finds each one and pairs it with the nearest printed price to its left or below (small cards: symbol right of the price; large cards: symbol above it). The list is given to the extractor as a hint and cross-checked after extraction: symbol on a card whose product is not a medicine → blocking; medicine with no symbol → review; no symbol found in the whole PDF → warning (layout changed, check by hand). Checked on the 3 fixtures: matches the Oct–Nov golden exactly.
- Known medicine brands (`compliance.yaml` → `medicines.known_brands`, prefix match on the product name: "Nurofen" matches "NurofenXS"): a match that is not `farmaco` + `is_medicine` is blocking. Products confirmed on the card as not medicines go in `medicines.not_medicine_exceptions` (regex). Brands with many devices/supplements (Bisolvon, Gaviscon, Fluimucil) are kept out of the list.
- Loyalty: reward and threshold are read from the flyer every month (it changed from €2/€20 to €3/€30); never reused from config.
- Cross-check: every price string found in the PDF text layer appears in `FlyerData` (and vice versa). Mismatches are flagged with `needs_review=True`.

Compliance checks on the content pack (`config/compliance.yaml`, editable):
- **Medicines (`is_medicine == True`)** are flagged for manual review by default. The configured mandatory warning is appended by code. Wording must be confirmed with the pharmacy owner before go-live.
- Forbidden claim patterns (e.g. "cura", "guarisce", "elimina", "miracoloso", "senza effetti collaterali", "garantito") on any health product; regex + LLM critic.
- Supplements: no disease-prevention or treatment claims.
- Health claims only verbatim from the flyer's own `description` line; the LLM never adds new benefits.
- Any post or slide with prices carries the legal footer lines from `FlyerData.legal_footer` (post caption end or image small print).
- My Agorà-only prices are always labelled "Solo con carta My Agorà"; loyalty copy repeats the exclusions.
- No prices or dates in LLM-written text (only placeholders).
- Every post references at least one existing product or service.
- Publish dates fall within the validity window; services are promoted before their date.
- Caption length, hashtag count and emoji policy per `channels.yaml` and `brand.yaml`.

Output: `ComplianceReport` with `blocking` and `warning` lists, each item pointing to the output and the rule.

## 8. LLM usage (multi-provider)

The core never imports a vendor SDK. Every AI step is a **task** with its own provider and model, set in `config/app.yaml`:

| Task | Needs | Suggested default |
| --- | --- | --- |
| `extract` | Reads PDF or page images, returns strict JSON | A strong vision model (Claude Sonnet, GPT-4-class, Gemini Pro) |
| `copy_social` | Italian copywriting in brand tone | Any strong model; cheaper ones are worth testing |
| `copy_screens` | Very short headlines | Small/cheap model |
| `compliance_critic` | Careful reading, temperature 0 | A different provider from the copy task (second opinion) |

Port (`ports/llm.py`):

```python
class LLMClient(Protocol):
    capabilities: Capabilities        # pdf_input, image_input, json_schema, max_images, max_tokens
    def structured(self, prompt: str, inputs: list[Part], schema: type[T],
                   temperature: float) -> LLMResult[T]: ...
    def text(self, prompt: str, inputs: list[Part], temperature: float) -> LLMResult[str]: ...

Part = TextPart | ImagePart | PdfPart          # provider-neutral inputs
LLMResult = {value, provider, model, input_tokens, output_tokens, cost_eur, latency_s, request_id}
```

Adapters (`adapters/llm/`), each a thin wrapper on the official SDK:
- **Anthropic** (`anthropic`): PDF as document block, structured output via tool use with the JSON schema.
- **OpenAI** (`openai`): structured outputs / JSON schema response format; PDF as file input or page images.
- **Google Gemini** (`google-genai`): PDF inline, `response_schema` for JSON.
- **OpenAI-compatible** (`openai` SDK with `base_url`): Mistral, Groq, Together, Ollama, vLLM. Page images instead of PDF when the model has no PDF input; JSON mode + validation when there is no schema support.

Rules shared by all adapters (`adapters/llm/base.py`):
- **Input fallback:** if `capabilities.pdf_input` is false, send rendered page images (from `ingest`); if images are not supported either, refuse the `extract` task at startup with a clear error.
- **Schema fallback:** if native JSON-schema output is missing, put the schema in the prompt, ask for JSON only, strip code fences, then validate with Pydantic.
- Parse, validate and retry once with the validation errors appended; then fail the stage (never pass unvalidated data on).
- Prompts are provider-neutral Markdown in `prompts/*.vN.md` (no vendor-specific tags). Optional per-provider overrides in `prompts/overrides/<provider>/` only if a model needs them.
- Temperature: 0 for `extract` and `compliance_critic`; 0.7 for copy tasks.
- Few-shot examples from `config/examples/` (first: the 21 Oct 2026 teaser caption).
- Extraction prompt describes the flyer anatomy in §1a and asks for one object per card.
- Prices per 1M tokens per model live in `config/pricing.yaml` (edit when vendors change prices); cost guard aborts a run above `max_cost_eur_per_run`.
- Manifest records provider, model, prompt version, tokens, cost and request id for every call, so outputs are traceable.
- **Provider comparison:** `flyer eval --providers anthropic,openai,gemini` runs `extract` on the 3 golden flyers and `copy_social` on one flyer per provider and writes a scorecard (extraction accuracy, compliance issues, cost, latency) to `tests/eval/`.
- Verify current model ids and SDK features in each vendor's docs before writing the adapter.

## 9. CLI

```bash
flyer ingest path/to/volantino.pdf            # creates run, prints run id
flyer extract <run>
flyer validate <run>                          # re-run after manual edits to flyer_data.json
flyer approve-data <run> --note "ok"
flyer generate <run>
flyer check <run>
flyer render <run>
flyer review <run>                            # opens review.html
flyer regen <run> --item post-03 --note "more playful, mention pharmacist advice"
flyer approve-pack <run>
flyer export <run>
flyer run path/to/volantino.pdf               # runs everything, stops at each gate
flyer status <run>
flyer eval --providers anthropic,openai,gemini   # compare providers on the golden flyers
flyer run path/to/volantino.pdf --provider gemini  # override the provider for one run
```

## 10. Testing strategy

- **Unit:** validators, discount math, date logic, planning, compliance rules, placeholder filling (no network).
- **Contract:** every Pydantic model round-trips JSON; JSON schemas snapshot-tested.
- **Integration:** full pipeline on fixture flyers with recorded LLM responses (cassettes), asserting outputs exist and validate.
- **Rendering:** snapshot test the HTML; check PNG sizes.
- **Golden files:** in M1, run extraction on the 3 fixtures, correct the output by hand at Gate 1, and save it as `*.golden.json`. Every later prompt or model change is scored against these files automatically.
- **Eval (manual, per prompt change):** run on the 3 fixture flyers. Score extraction accuracy (product/price exact match ≥ 98%) and compare generated copy with what we actually published. Keep a markdown scorecard in `tests/eval/`.
- CI target: `ruff`, `mypy`, `pytest` green before each milestone is closed.

## 11. Milestones

| # | Milestone | Done when |
| --- | --- | --- |
| M0 | Skeleton | Repo, `pyproject`, config loading, models, ports, LLM registry + first adapter + a fake adapter for tests, CLI `status`, CI checks pass |
| M0.5 | Second LLM provider | A second adapter passes the same contract tests; switching provider in `app.yaml` changes nothing else |
| M1 | Ingest + extract | `flyer extract` runs on all 3 fixtures; first outputs hand-checked and saved as golden files `tests/fixtures/flyers/*.golden.json`; ≥ 98% exact match on name + prices + badges vs golden; 100% of promotions, services and loyalty offers found |
| M2 | Validation + Gate 1 | Validation report, `review.html` data table, `approve-data` with manifest record |
| M3 | Generate + compliance | Content pack JSON for teaser, posts, stories, screens; compliance report with blocking rules |
| M4 | Render | Teaser, post, story and screen PNGs at correct sizes using brand templates |
| M5 | Gate 2 + regen + export | Gallery review, single-item regeneration, zip export, PED-compatible CSV |
| M6 | Demo hardening | End-to-end on a fixture flyer not used for prompt tuning (no Nov–Dec 2026 flyer available) in < 10 min machine time; cost per run logged; provider comparison (`flyer eval --providers`) on the 3 golden flyers with a scorecard; 3-minute demo recorded |
| M7 | Drive + Sheet agent (§14) | A PDF dropped in a Drive folder produces the review sheet without anyone running a command; both gates work by ticking a box; edits and notes in the sheet are applied as in §14.5; final pack lands in `Pronto da pubblicare`; full flow on one fixture flyer with a test Drive folder |

## 12. Inputs to collect before M1

- [x] 3 past flyers as PDF — in `tests/fixtures/flyers/` (Jul–Aug 2025, May 2026, Oct–Nov 2026)
- [x] 1 published social post (flyer teaser) — in `tests/fixtures/social/`
- [x] ~~Nov–Dec 2026 flyer PDF~~: not available; the demo uses the fixture flyers (decided 4 Nov 2026)
- [ ] More published posts for those flyers: at least one product post, one service post and one My Agorà post (for few-shot examples and eval)
- [x] Farmagorà logo (horizontal, colour) — `assets/logo-farmagora-orizzontale.jpg`; colours #015176 / #FED061
- [ ] Logo as SVG or transparent PNG, white/negative version, brand fonts
- [ ] Store name, address, opening hours, booking channel for services
- [ ] Compliance wording confirmed by the pharmacy owner (mandatory warnings, forbidden claims)
- [x] At least one LLM API key in `.env` (Gemini, free tier). Two needed for the provider comparison in M6
- [ ] Paid LLM key for reliable runs (free tier: no Pro models, frequent 503s)
- [ ] For M7: Google Cloud project with an OAuth client (Desktop app) and the owner's Google account, root Drive folder (see §14.9)

## 13. Later (not in v1)

- ~~Google Drive watcher~~ → moved into scope as M7 (§14).
- Publisher adapters: Brevo/Mailchimp campaign draft, Meta Business Suite scheduling, in-store screen CMS upload.
- Multi-store variants and multiple approvers with roles.
- Learning loop: store approval edits and use them as new few-shot examples.

## 14. Drive + Sheet agent (M7)

**Why.** The flyer arrives once a month. A website, an MCP server or a Slack bot is too much to install, learn and maintain for that rhythm, and Farmagorà has no Slack and may not have Claude Code. The agent therefore works **inside tools the team already uses**: a Google Drive folder and a Google Sheet. Nothing to install, nothing to remember; the agent tells the approver by email when it needs them.

The pipeline (§6), validation (§7) and code guarantees stay exactly as they are. M7 adds a front end (Drive + Sheet + email) and a scheduler on top. The agent can trigger a gate, but the code still refuses if anything is blocking.

### 14.0 Demo variant: Google Drive desktop sync (M7a, built)

Chosen for the demo (4 Nov 2026): no Google Cloud project, no OAuth. One small dependency (`openpyxl`) for the review spreadsheet. Everything works from Drive in the browser: the approver never needs the Drive app; only the Mac running the agent syncs the folder. Google Drive for desktop syncs the shared folder to this Mac; `flyer watch` (running on the Mac) treats it as a local folder (`drive.watch_dir` in `config/app.yaml` or `--folder`).

| Approver does | Agent does (`src/flyer_agent/stages/watch.py`, decisions in `core/folder_flow.py`) |
| --- | --- |
| Creates `Volantino maggio/` and drops the PDF | Waits until the file is synced (20 s unchanged), ingest + extract; writes `Risultati agente/1 - Dati letti dal volantino/` (`Controlla i dati.pdf`), `Revisione.xlsx` and `DA APPROVARE - dati.txt` (issues + instructions) |
| Corrects yellow cells in `Revisione.xlsx` → tab `Prodotti` (Drive opens it in Google Sheets and saves back to the same `.xlsx`) | Applies the readable cells (`apply_data_edits`, recorded in the manifest), lists unreadable ones, re-runs every data check, refreshes the PDF and `DA APPROVARE - dati.txt`. The sheet itself is not rewritten while the approver may be editing it |
| Renames `DA APPROVARE - dati.txt` → `APPROVATO - dati.txt` | Applies pending sheet edits first; Gate 1 with an approval record (refused and file restored with the reasons if anything is blocking or a cell could not be read); generate, check, render; writes `Risultati agente/2 - Contenuti da approvare/` (`Post/`, `Storie/`, `Schermi/`, `Didascalie.md`, `Calendario.csv`, `Controlla i contenuti.pdf`), tab `Contenuti` in `Revisione.xlsx` (one row per post, story and screen), `DA APPROVARE - contenuti.txt` |
| Writes `più breve` in the yellow `Modifica richiesta` column of `Contenuti` (legacy: `post-03: più breve` in `NOTE.txt`) | Regenerates only those items, marks the row `✓ applicata`, re-checks, re-renders; any `APPROVATO - contenuti` file is removed (new content must be approved again) |
| Renames to `APPROVATO - contenuti.txt` | Gate 2 with an approval record, export; everything + zip in `Risultati agente/3 - Pronto da pubblicare/` |

Errors (provider busy, quota) go to `ERRORE.txt` and are retried on the next scan; a new or replaced PDF starts a new run and clears old approvals. Review pages are PDFs because Drive shows HTML as code. Limits: works only while the Mac is on and `flyer watch` runs; no email (macOS notification instead); if the approver and the agent write the sheet at the same moment, the later save wins (the agent only rewrites it at step changes). The API + Sheet design below (§14.1–14.11) remains the production target.

### 14.0b Drive API variant (M7b, built 5 Nov 2026)

Drive for desktop proved unreliable (sync stalled twice after the Mac slept) and the client will use Drive only in the browser. `flyer watch` with `drive.mode: api` works on the folder online: each scan it pulls the approver's top-level changes (PDF, renamed approval files, `Revisione.xlsx`), runs the same `process_folder` on a local working copy (`runs/drive-cache/<folder id>/`), and pushes the agent's results back (`core/mirror.py` plans from checksums recorded at the last sync; `stages/drive_sync.py`; `adapters/gdrive.py`). `_agent/` stays local. A top-level file changed online while the agent worked is never overwritten. Auth: OAuth desktop flow as the folder owner (`credentials.json`, token in `.secrets/`), because a service account cannot own files in My Drive. Same code runs on a server later.

### 14.1 Flow (approver's view)

1. **Drop.** The approver creates `Volantini Farmagorà/Volantino dicembre/` and puts the flyer PDF in it. That is the only setup step.
2. **Read** (agent, within ~15 min). It finds the new PDF, runs `ingest` + `extract` + `validate`, creates the sheet `Volantino dicembre – Revisione` in the same folder, and sends an email: *"Ho letto il volantino di dicembre: 54 prodotti, 0 problemi bloccanti, 3 da controllare."*
3. **Gate 1** (approver, ~10 min). Tab `Prodotti`: rows needing attention are highlighted at the top with the reason. The approver checks them against the PDF, fixes cells if needed, ticks **Dati approvati**. If anything is still blocking, the agent unticks the box and writes the reason in red.
4. **Create** (agent, ~10 min). `generate` + `check` + `render`. Images go into `Post/`, `Storie/`, `Schermi/`; tab `Contenuti` is filled; email: *"Contenuti pronti: 12 post, 6 storie, 12 schermi. 2 post con farmaci da controllare."*
5. **Gate 2** (approver, ~10–15 min). In `Contenuti`, each row is OK, has a note for the AI, has edited text, or is excluded. Rows marked `da rifare` come back on the next cycle (email when done). When everything is OK or excluded, the approver ticks **Approvato**.
6. **Export** (agent). Final images, captions and calendar go into `Pronto da pubblicare/`; the calendar is also copied into the PED Social sheet (or provided as CSV until the sheet format is confirmed). Upload to social networks and screens stays manual.

Target human time: **≤ 30 minutes per flyer** (same as §1).

### 14.2 Drive folder layout

```
Volantini Farmagorà/                      # root folder, in a Shared Drive (see 14.9)
└── Volantino dicembre/                   # one folder per flyer, any name
    ├── volantino-dicembre-2026.pdf       # dropped by the approver (exactly one PDF)
    ├── Volantino dicembre – Revisione    # Google Sheet created by the agent
    ├── Post/  Storie/  Schermi/          # rendered PNGs (after step 4)
    ├── Pronto da pubblicare/             # final pack (after Gate 2)
    └── _agent/                           # run folder mirror: manifest.json, flyer_data.json, content_pack.json, logs. Do not edit.
```

A folder is picked up when it contains exactly one PDF and no `_agent/` folder. Two PDFs, or a non-PDF only, produce an email asking to fix the folder. If a new PDF replaces the old one, a new run starts (runs are keyed by SHA-256, §2) and the old sheet is renamed `… (vecchio)`.

### 14.3 Sheet layout

All labels in Italian (user-facing). Columns in grey are written by the agent and protected; white columns are editable.

**Tab `Riepilogo`:** flyer title, validity, run state, counts (products, issues), checkboxes **Dati approvati** and **Approvato**, last agent update, link to the PDF.

**Tab `Prodotti`** (Gate 1), one row per product, issue rows first:

| Column | Editable | Maps to |
| --- | --- | --- |
| `Controllo` (🔴 bloccante / 🟡 da controllare / ✅) + `Motivo` | no | validation issues |
| `ID` | no | `Product.id` |
| `Nome`, `Marca`, `Formato`, `Descrizione`, `Categoria volantino` | yes | same fields |
| `Tipo` (dropdown of `product_type` values) | yes | `product_type` |
| `Farmaco` (sì/no) | yes | `is_medicine` |
| `Prezzo`, `Prezzo barrato`, `Sconto %` | yes | `Price` |
| `Solo My Agorà`, `Prodotto Farmagorà`, `Imperdibile` (checkbox) | yes | badges |
| `Gruppo prezzo`, `Pagina` | yes | `price_group`, `page` |

**Tab `Promozioni e servizi`:** same idea for `Promotion`, `ServiceOffer`, `LoyaltyOffer` (including My Agorà exclusions).

**Tab `Contenuti`** (Gate 2), one row per post, story and screen slide:

| Column | Editable | Meaning |
| --- | --- | --- |
| `ID`, `Tipo` (post/storia/schermo), `Argomento` | no | item identity |
| `Data` | yes | publish date (must stay within validity) |
| `Anteprima` | no | link to the PNG in Drive |
| `Titolo immagine` | yes | `image_headline` / slide headline |
| `Testo post` | yes | caption as shown to the public (placeholders already filled) |
| `Avvertenze` | no | disclaimers added by code (medicine warning, My Agorà label) |
| `Controllo` + `Motivo` | no | compliance result for this row |
| `Nota per l'AI` | yes | free-text instruction for a rewrite |
| `Stato` (OK / da rifare / escludi) | yes | what the agent should do |

**Tab `Registro`:** append-only log (time, action, result, provider/model, tokens, cost), so the approver can see what the agent did.

### 14.4 What triggers the agent

A scheduled job runs `flyer watch --once` every 15 minutes. On each run, for every flyer folder:

| Situation | Agent action |
| --- | --- |
| New folder with one PDF | ingest → extract → validate → create sheet → email |
| `Prodotti` / `Promozioni e servizi` edited since last cycle | read rows → `FlyerData` → validate → update `Controllo` columns |
| **Dati approvati** ticked | validate; if blocking → untick + reason; else `approve-data` (approval record) → generate → check → render → fill `Contenuti` → email |
| Rows with `Stato = da rifare` or a new `Nota per l'AI` | `regen` those items with the note → check → render → set `Stato` back to blank for review → email |
| `Testo post` / `Titolo immagine` / `Data` edited by hand | check that row → re-render that image → keep the edit |
| **Approvato** ticked | if any blocking issue → untick + reason; else `approve-pack` → export to `Pronto da pubblicare/` → PED copy → email |
| Error (LLM 503, quota, rendering) | retry with backoff inside the cycle; if still failing, log in `Registro`, email once, retry next cycle |

The agent acts only on these signals, never on a half-typed cell in the middle of an edit: data edits are validated, but nothing is generated until a box is ticked or a row is marked `da rifare`. One run per folder at a time (lock file in `_agent/`).

### 14.5 Edit rules

- **Data edits** (tab `Prodotti`) are the new source of truth after Gate 1. The same validation as §7 applies. Changing a price or the medicine flag after content exists marks every affected `Contenuti` row as `da rifare`.
- **Manual text is never overwritten.** The agent stores the hash of what it wrote in each editable cell. If the cell differs, it is a manual edit: the agent checks and renders it, but never rewrites it, unless the row is marked `da rifare`.
- **Prices and dates typed by hand.** The sheet shows captions with prices filled in. When reading a caption back, the agent turns any price that exactly matches a product in the post into its placeholder (`{price:<id>}`, `{old_price:<id>}`, `{discount:<id>}`, `{valid_to}`). Any other number that looks like a price, discount or date is blocking, with the reason in `Motivo`. This keeps the "0 price errors" guarantee (§1) even with manual edits.
- **Compliance on manual text** is the same as on AI text (§7): forbidden claims are blocking, and mandatory warnings are added by code and cannot be deleted from the sheet.
- **Excluded rows** (`Stato = escludi`) are left out of the export and the calendar, but kept in the sheet.
- **Own image.** If the approver puts a PNG with the same name into `Post/`, `Storie/` or `Schermi/`, the agent uses it as-is and marks the row "immagine manuale" (not re-rendered).
- **Layout, colours and fonts** are not editable from the sheet. They live in `templates/` and `config/brand.yaml` and change for all future flyers.

### 14.6 Architecture

New ports and adapters (core stays pure, §2):

| Piece | Where | Notes |
| --- | --- | --- |
| `ports/storage.py` → `adapters/drive_storage.py` | Drive folder ↔ local run folder | Download PDF, upload PNGs and `_agent/`. The local run folder stays the working copy; Drive is the shared copy. |
| `ports/review_sheet.py` → `adapters/google_sheet.py` | Create/format the sheet, read and write rows, protected ranges, checkboxes | |
| `core/sheet_mapping.py` | pure | `FlyerData` / `ContentPack` ↔ rows; price-to-placeholder conversion; manual-edit detection by hash |
| `ports/notifier.py` → `adapters/email_gmail.py` | Italian email templates in `templates/email/` | Gmail API with the owner's login; recipient is the owner only |
| `stages/watch.py` | the decision table of §14.4 | calls the existing stages |
| CLI | `flyer watch --once`, `flyer watch --folder <id>`, `flyer sync <run>` | `--once` is what the scheduler runs |

### 14.7 Data contract changes (ask before changing `core/models.py`)

Needed in `SocialPost` / `ScreenSlide` (or a new `ContentItemState`): `status` (`ok` / `redo` / `excluded`), `note`, `manual_fields` (which fields were edited by hand), `manual_image` (bool), `written_hash` per editable field. JSON schema snapshots updated in the same change.

### 14.8 Dependencies (not yet in §3: approval needed)

- `google-api-python-client` + `google-auth` + `google-auth-oauthlib`: Drive, Sheets and Gmail APIs with the owner's account.
- Email: Gmail API with the same login, sent to the owner only (stdlib `smtplib` is the fallback).
- Hosting: a container image with Chromium for Playwright (`Dockerfile`).

### 14.9 Hosting and setup

- **Scheduler:** Google Cloud Run job + Cloud Scheduler every 15 minutes (nearly free at one flyer a month). Alternative: any always-on machine with `cron`/`launchd`.
- **Drive (decided 4 Nov 2026):** the owner's own **My Drive**, accessed with the owner's Google account (OAuth, refresh token stored as a secret), not a service account: service accounts have no storage quota of their own and cannot reliably create files in a personal Drive. When the client takes over in production, switch to a Shared Drive + service account or the client's own account.
- **Secrets** in `.env` locally or the job's secret store, never in Drive or the image: LLM key, Google OAuth client + refresh token.
- **LLM:** paid key (free tier is not reliable enough, see §0).

### 14.10 Rules and scope

- Still **no publishing**: the agent writes only to the Drive folder, the PED sheet and the owner's inbox. Emails are notifications to the owner, never to the public. `CLAUDE.md` updated accordingly (approved 4 Nov 2026).
- **Approval record:** the Sheets API does not say who ticked a box. v1 records the configured approver email, the time and the sheet revision id. If several people can approve, read the editor from the Drive Activity API (later).
- The static `review.html` and the CLI keep working for developers and offline demos.

### 14.11 Decisions and open questions

Decided (4 Nov 2026):
- For the demo and until the client approves going to production, **our team** drops the PDF and approves; the owner is the only approver and email recipient. Handover to Farmagorà after approval.
- Drive: the owner's My Drive; email: the owner's Gmail.

Open:
1. Write into the PED Social sheet directly (need its link and column format) or provide a calendar tab to copy from?
2. Root folder name.
3. Is 15 minutes fast enough, or should the agent also run on demand (e.g. a "Aggiorna ora" checkbox in `Riepilogo`)?
4. Production: who at Farmagorà approves, and which Google account/Drive they use.

