"""Pipeline stages. Each stage reads typed JSON from the run folder and writes its outputs back."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..adapters import pdf as pdfio
from ..adapters.llm.offline_llm import CONTEXT_TAG
from ..adapters.llm.registry import build_client
from ..config import Config
from ..core import compliance, planning, state
from ..core.merge import merge_parts, page_chunks
from ..core.models import (
    Approval,
    ComplianceReport,
    ContentPack,
    FlyerData,
    Issue,
    LLMCallRecord,
    Manifest,
    PostCopy,
    PostSpec,
    ScreenCopyBatch,
    ScreenSlide,
    SocialCopyBatch,
    SocialPost,
)
from ..core.placeholders import PlaceholderError, day_month, eur, eur_short, fill
from ..core.review_sheet import DataEdits, apply_product_rows
from ..core.validation import validate as validate_data
from ..ports.llm import LLMResult, PdfPart, TextPart

VERSION_RE = re.compile(r"<!--\s*version:\s*([\w.\-]+)\s*-->")


# ---------------------------------------------------------------- run storage
class Run:
    def __init__(self, cfg: Config, run_id: str):
        self.cfg, self.id = cfg, run_id
        self.dir = cfg.runs_dir / run_id

    # files
    def path(self, name: str) -> Path:
        return self.dir / name

    def save(self, name: str, obj: BaseModel | Any) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        text = obj.model_dump_json(indent=2, by_alias=True) if isinstance(obj, BaseModel) \
            else json.dumps(obj, indent=2, ensure_ascii=False, default=str)
        p.write_text(text, encoding="utf-8")
        return p

    def load(self, name: str, model: type[BaseModel]) -> Any:
        return model.model_validate_json(self.path(name).read_text(encoding="utf-8"))

    # manifest
    @property
    def manifest(self) -> Manifest:
        return self.load("manifest.json", Manifest)

    def advance(self, stage: str, note: str = "") -> Manifest:
        m = self.manifest
        m.state = state.next_state(stage, m.state)  # type: ignore[assignment]
        m.updated_at = datetime.now()
        m.history.append(f"{m.updated_at:%Y-%m-%d %H:%M} {stage}{(': ' + note) if note else ''}")
        self.save("manifest.json", m)
        return m

    def require(self, stage: str) -> None:
        m = self.manifest
        if not state.can_run(stage, m.state):
            raise state.StateError(f"'{stage}' needs state {state.REQUIRES[stage]} or later; run is {m.state}")

    def record(self, task: str, prompt_version: str, res: LLMResult) -> None:
        price = (self.cfg.pricing or {}).get(res.model) or {}
        cost = (res.input_tokens * float(price.get("input", 0)) + res.output_tokens * float(price.get("output", 0))) / 1e6
        m = self.manifest
        m.llm_calls.append(LLMCallRecord(task=task, provider=res.provider, model=res.model,
                                         prompt_version=prompt_version, input_tokens=res.input_tokens,
                                         output_tokens=res.output_tokens, cost_eur=round(cost, 5),
                                         latency_s=res.latency_s, at=datetime.now()))
        self.save("manifest.json", m)
        limit = float(self.cfg.app.get("max_cost_eur_per_run", 1e9))
        if m.cost_eur > limit:
            raise RuntimeError(f"cost guard: run cost €{m.cost_eur} > max_cost_eur_per_run €{limit}")


def find_run(cfg: Config, run_id: str | None) -> Run:
    if run_id:
        matches = [p for p in cfg.runs_dir.glob(f"{run_id}*") if p.is_dir()]
        if len(matches) != 1:
            raise SystemExit(f"run '{run_id}' not found (or ambiguous)")
        return Run(cfg, matches[0].name)
    runs = sorted((p for p in cfg.runs_dir.glob("*") if (p / "manifest.json").exists()),
                  key=lambda p: p.stat().st_mtime)
    if not runs:
        raise SystemExit("no runs yet: use `flyer ingest <pdf>`")
    return Run(cfg, runs[-1].name)


def _prompt(cfg: Config, name: str) -> tuple[str, str]:
    text = (cfg.root / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    m = VERSION_RE.search(text)
    return VERSION_RE.sub("", text).strip(), (m.group(1) if m else name)


def _client(cfg: Config, task: str):
    t = cfg.task(task)
    return build_client(t["provider"], t.get("model", ""), cfg.app["llm"].get("providers", {})), t


# ---------------------------------------------------------------- stages
def ingest(cfg: Config, pdf: Path) -> Run:
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    run = Run(cfg, digest[:12])
    run.dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, run.path("source.pdf"))
    pages = pdfio.render_pages(run.path("source.pdf"), run.path("pages"))
    run.save("text.json", {"pages": pdfio.text_layer(run.path("source.pdf"))})
    run.save("symbols.json", {"medicine_symbols": pdfio.medicine_symbols(run.path("source.pdf"))})
    run.save("photos.json", {"product_photos": pdfio.product_photos(run.path("source.pdf"))})
    now = datetime.now()
    if not run.path("manifest.json").exists():
        run.save("manifest.json", Manifest(flyer_id=digest, source_name=pdf.name, state="INGESTED",
                                           created_at=now, updated_at=now,
                                           history=[f"{now:%Y-%m-%d %H:%M} ingest: {pdf.name} ({len(pages)} pages)"]))
    return run


def reopen_for_review(run: Run) -> tuple[FlyerData, list[Issue]] | None:
    """Same PDF dropped again (e.g. in a new folder): reuse the existing reading instead of calling the LLM again,
    and go back to Gate 1 so both approvals are given again. None if the PDF was never read."""
    if run.manifest.state == "INGESTED" or not run.path("flyer_data.json").exists():
        return None
    m = run.manifest
    if m.state != "EXTRACTED":
        m.history.append(f"{datetime.now():%Y-%m-%d %H:%M} reopen: same PDF dropped again, back to Gate 1 "
                         f"(was {m.state}; earlier approvals kept as history only)")
        m.state = "EXTRACTED"
        m.updated_at = datetime.now()
        run.save("manifest.json", m)
    return run.load("flyer_data.json", FlyerData), revalidate(run)


def extract(run: Run) -> tuple[FlyerData, list[Issue]]:
    run.require("extract")
    cfg = run.cfg
    client, task = _client(cfg, "extract")
    prompt, version = _prompt(cfg, "extract_flyer.v3")
    pages = tuple(sorted(run.path("pages").glob("page-*.png")))
    text = "\n\n".join(f"--- pagina {i} ---\n{t}" for i, t in
                       enumerate(json.loads(run.path("text.json").read_text())["pages"], 1))
    temperature = float(task.get("temperature", 0))
    caps = client.capabilities
    if caps.pdf_input or len(pages) <= caps.max_images:
        inputs = [PdfPart(path=run.path("source.pdf"), page_images=pages),
                  TextPart(text="TESTO ESTRATTO DAL PDF (può essere in disordine, usalo solo per verificare):\n" + text),
                  TextPart(text=_symbols_hint(_symbols(run)))]
        res = client.structured(system=EXTRACT_SYSTEM, prompt=prompt, inputs=inputs, schema=FlyerData,
                                temperature=temperature)
    else:
        res = _extract_in_batches(run, client, prompt, pages, temperature)
    run.record("extract", version, res)
    data: FlyerData = res.value
    data.flyer_id = run.manifest.flyer_id
    data.source_pages = len(pages)
    data.theme.cover_image_ref = str(pages[0].relative_to(run.dir))
    data.theme.accent_hex = pdfio.accent_color(pages[0])
    _attach_photos(run, data)
    run.save("flyer_data.json", data)
    issues = _validate(run, data)
    run.advance("extract", f"{len(data.products)} products via {res.provider}/{res.model}")
    return data, issues


EXTRACT_SYSTEM = "Estrai dati strutturati dai volantini Farmagorà."


def _extract_in_batches(run: Run, client: Any, prompt: str, pages: tuple[Path, ...],
                        temperature: float) -> LLMResult:
    """For models with few images per request: read the flyer in page batches and merge the results."""
    texts = json.loads(run.path("text.json").read_text())["pages"]
    symbols = _symbols(run)
    parts, tin, tout, secs = [], 0, 0, 0.0
    last = None
    for chunk in page_chunks(len(pages), client.capabilities.max_images):
        shown = sorted({1, *chunk})  # the cover text always travels: title, validity, theme
        text = "\n\n".join(f"--- pagina {i} ---\n{texts[i - 1]}" for i in shown)
        note = (f"\n\n# Parte del volantino\nVedi SOLO le pagine {chunk[0]}–{chunk[-1]} di {len(pages)} "
                "(le immagini sono in quest'ordine). Estrai prodotti, promozioni e servizi SOLO di queste pagine, "
                "con il loro vero numero di pagina. Titolo, validità e tema: copiali dalla copertina "
                "(testo di pagina 1) anche se non vedi la copertina.")
        inputs = [PdfPart(path=run.path("source.pdf"), page_images=tuple(pages[i - 1] for i in chunk)),
                  TextPart(text="TESTO ESTRATTO DAL PDF (può essere in disordine, usalo solo per verificare):\n" + text),
                  TextPart(text=_symbols_hint([s for s in symbols if s["page"] in chunk]))]
        last = client.structured(system=EXTRACT_SYSTEM, prompt=prompt + note, inputs=inputs, schema=FlyerData,
                                 temperature=temperature)
        parts.append(last.value)
        tin, tout, secs = tin + last.input_tokens, tout + last.output_tokens, secs + last.latency_s
    assert last is not None
    return LLMResult(value=merge_parts(parts), provider=last.provider, model=last.model, input_tokens=tin,
                     output_tokens=tout, latency_s=round(secs, 2))


def _attach_photos(run: Run, data: FlyerData) -> None:
    """Give products without a bbox the photo found by code next to their price (same page, reading order)."""
    if not run.path("photos.json").exists():
        run.save("photos.json", {"product_photos": pdfio.product_photos(run.path("source.pdf"))})
    free: dict[tuple[int, str], list[list[float]]] = {}
    for ph in json.loads(run.path("photos.json").read_text())["product_photos"]:
        free.setdefault((ph["page"], ph["price"]), []).append(ph["bbox"])
    for p in data.products:
        if p.bbox:
            continue
        slots = free.get((p.page, _eur_key(p.price.current_eur)))
        if slots:
            p.bbox = slots.pop(0) if len(slots) > 1 else slots[0]  # shared price card: last photo is reused


def _eur_key(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def _symbols(run: Run) -> list[dict]:
    """Medicine symbols found by code in the PDF (computed and saved on first use for older runs)."""
    if not run.path("symbols.json").exists():
        run.save("symbols.json", {"medicine_symbols": pdfio.medicine_symbols(run.path("source.pdf"))})
    return json.loads(run.path("symbols.json").read_text())["medicine_symbols"]


def _symbols_hint(symbols: list[dict]) -> str:
    paired = [s for s in symbols if s["price"]]
    if not paired:
        return "SIMBOLI DEL FARMACO TROVATI DAL PROGRAMMA: nessuno (controlla tu ogni scheda)."
    lines = [f"- pagina {s['page']}: simbolo accanto al prezzo €{s['price']}" for s in paired]
    return ("SIMBOLI DEL FARMACO TROVATI DAL PROGRAMMA (posizione esatta letta dal PDF; il prezzo indicato è "
            "quello della scheda a cui appartiene il simbolo, nuovo o barrato):\n" + "\n".join(lines))


def _validate(run: Run, data: FlyerData) -> list[Issue]:
    text = "\n".join(json.loads(run.path("text.json").read_text())["pages"])
    med = run.cfg.compliance.get("medicines", {})
    symbols = [(s["page"], s["price"]) for s in _symbols(run) if s["price"]]
    issues = validate_data(data, text, medicine_brands=med.get("known_brands") or [],
                           not_medicine_exceptions=med.get("not_medicine_exceptions") or [],
                           medicine_symbols=symbols)
    run.save("validation.json", [i.model_dump() for i in issues])
    from .review import build_review
    build_review(run)
    return issues


def revalidate(run: Run) -> list[Issue]:
    run.require("validate")
    return _validate(run, run.load("flyer_data.json", FlyerData))


def apply_data_edits(run: Run, rows: list[dict], by: str) -> tuple[DataEdits, list[Issue]]:
    """Gate 1 corrections from the review spreadsheet: apply, record in the manifest, re-run every data check."""
    run.require("approve-data")
    if run.manifest.state != "EXTRACTED":
        raise state.StateError("data can only be corrected before Gate 1 (state EXTRACTED)")
    edits = apply_product_rows(run.load("flyer_data.json", FlyerData), rows)
    if edits.changed:
        run.save("flyer_data.json", edits.data)
        m = run.manifest
        m.history.append(f"{datetime.now():%Y-%m-%d %H:%M} data edits by {by}: " + "; ".join(edits.changes))
        run.save("manifest.json", m)
    return edits, _validate(run, edits.data)


def approve(run: Run, gate: str, by: str, note: str) -> Manifest:
    if gate == "data":
        run.require("approve-data")
        issues = revalidate(run)
        blocking = [i for i in issues if i.severity == "blocking"]
        if blocking:
            raise SystemExit(f"cannot approve: {len(blocking)} blocking issue(s). Fix flyer_data.json, then validate.")
        stage = "approve-data"
    else:
        run.require("approve-pack")
        stage = "approve-pack"
    m = run.advance(stage, note)
    m.approvals.append(Approval(gate=gate, by=by, at=datetime.now(), note=note))  # type: ignore[arg-type]
    run.save("manifest.json", m)
    from .review import build_review
    build_review(run)
    return m


def _context(data: FlyerData, posts: list[PostSpec] | None = None, screens: list | None = None) -> str:
    """Flyer facts for the copy prompts. With posts/screens, only the products they mention are included,
    to keep requests small (free tiers limit tokens per minute)."""
    wanted: set[str] | None = None
    if posts is not None or screens is not None:
        wanted = {i for s in posts or [] for i in (*s.product_ids, *s.ref_ids)}
        wanted |= {s.product_id for s in screens or []}
    ctx: dict[str, Any] = {
        "flyer": {"title": data.title, "headline": data.theme.headline, "valid_from": str(data.valid_from),
                  "valid_to": str(data.valid_to)},
        "products": {p.id: p.model_dump(mode="json", include={"id", "name", "format", "description", "flyer_category",
                                                              "is_medicine", "my_agora_only", "hero", "product_type"})
                     for p in data.products if wanted is None or p.id in wanted},
        "services": {s.id: s.model_dump(mode="json") for s in data.services},
        "promotions": {p.id: p.model_dump(mode="json") for p in data.promotions},
        "loyalty": data.loyalty.model_dump(mode="json") if data.loyalty else None,
    }
    if posts is not None:
        ctx["posts"] = [s.model_dump(mode="json") for s in posts]
    if screens is not None:
        ctx["screens"] = [s.model_dump(mode="json") for s in screens]
    return CONTEXT_TAG + json.dumps(ctx, ensure_ascii=False)


def _social_prompt(cfg: Config) -> tuple[str, str]:
    prompt, version = _prompt(cfg, "copy_social.v2")
    ex = "\n".join(f"- ({e.get('topic')}) {e.get('caption')}" for e in cfg.examples) or "- (nessun esempio)"
    soc = cfg.channels["social"]
    prompt = (prompt.replace("{{ examples }}", ex).replace("{{ caption_max }}", str(soc["caption_max_chars"]))
              .replace("{{ hashtags_max }}", str(soc["hashtags_max"])))
    return prompt, version


def _write_copy(run: Run, data: FlyerData, specs: list[PostSpec], extra_note: str = "") -> dict[str, PostCopy]:
    """Captions for these posts/stories, in batches of `tasks.copy_social.batch_size` (default: all at once)."""
    client, task = _client(run.cfg, "copy_social")
    prompt, version = _social_prompt(run.cfg)
    if extra_note:
        prompt += f"\n\n# Nota del revisore\n{extra_note}"
    size = int(task.get("batch_size") or len(specs) or 1)
    got: dict[str, PostCopy] = {}
    for start in range(0, len(specs), size):
        batch = specs[start:start + size]
        res = client.structured(system="Copywriter social Farmagorà.", prompt=prompt,
                                inputs=[TextPart(text=_context(data, posts=batch))], schema=SocialCopyBatch,
                                temperature=float(task.get("temperature", 0.7)))
        run.record("copy_social", version, res)
        got |= {c.id: c for c in res.value.posts}
    missing = [s.id for s in specs if s.id not in got]
    if missing:
        raise RuntimeError(f"copy_social did not return: {', '.join(missing)}")
    return got


def _write_screen_heads(run: Run, data: FlyerData, specs: list, extra_note: str = "") -> dict[str, str]:
    """Headlines for screen slides, by slide id."""
    client, task = _client(run.cfg, "copy_screens")
    prompt, version = _prompt(run.cfg, "copy_screens.v2")
    if extra_note:
        prompt += f"\n\n# Nota del revisore\n{extra_note}"
    res = client.structured(system="Titoli per schermi in farmacia Farmagorà.", prompt=prompt,
                            inputs=[TextPart(text=_context(data, screens=specs))], schema=ScreenCopyBatch,
                            temperature=float(task.get("temperature", 0.7)))
    run.record("copy_screens", version, res)
    return {c.id: c.headline for c in res.value.screens}


def _finalise_post(post: SocialPost, data: FlyerData, rules: dict) -> SocialPost:
    post.disclaimers = compliance.disclaimers_for(post, data, rules)
    try:
        post.caption_final = fill(post.copy_.caption, data)
    except PlaceholderError:
        post.caption_final = ""  # reported as blocking by `check`
    return post


def generate(run: Run) -> ContentPack:
    run.require("generate")
    cfg = run.cfg
    data: FlyerData = run.load("flyer_data.json", FlyerData)
    soc, scr = cfg.channels["social"], cfg.channels["screens"]
    specs = planning.plan_posts(data, posts_max=soc["posts_per_flyer"][1], stories_max=soc["stories_per_flyer"][1],
                                last_call_days=soc["last_call_days_before_end"])
    copies = _write_copy(run, data, specs)
    posts = [_finalise_post(SocialPost(spec=s, copy=copies[s.id]), data, cfg.compliance) for s in specs]

    screen_specs = planning.plan_screens(data, max_slides=scr["max_slides"])
    heads = _write_screen_heads(run, data, screen_specs)
    screens = []
    for sp in screen_specs:
        p = data.product(sp.product_id)
        assert p
        disc = []
        if p.my_agora_only:
            disc.append(cfg.compliance["loyalty"]["label_card_only_prices"])
        if p.is_medicine:
            disc.append(cfg.compliance["medicines"]["mandatory_warning"])
        screens.append(ScreenSlide(
            spec=sp, headline=heads.get(sp.id, p.flyer_category), price_text=eur(p.price.current_eur),
            old_price_text=eur(p.price.previous_eur) if p.price.previous_eur else None,
            discount_text=f"-{p.price.discount_pct}%" if p.price.discount_pct else None,
            validity_text=f"Offerta valida fino al {day_month(data.valid_to)}",
            badge="SOLO CON MY AGORÀ" if p.my_agora_only else None, disclaimer=" · ".join(disc) or None))
    pack = ContentPack(flyer_id=data.flyer_id, posts=posts, screens=screens)
    run.save("content_pack.json", pack)
    run.advance("generate", f"{len(posts)} posts/stories, {len(screens)} screens")
    return pack


def check(run: Run) -> ComplianceReport:
    run.require("check")
    data = run.load("flyer_data.json", FlyerData)
    pack: ContentPack = run.load("content_pack.json", ContentPack)
    report = compliance.check(pack, data, run.cfg.compliance, run.cfg.channels)
    pack.compliance = report
    run.save("content_pack.json", pack)
    if report.blocking:
        return report  # state stays GENERATED: fix with `regen`, then check again
    run.advance("check", f"{len(report.issues)} issues, 0 blocking")
    return report


def regen(run: Run, item: str, note: str) -> str:
    """Rewrite one post, story or screen slide with a reviewer note. Returns the new text."""
    run.require("check")
    data = run.load("flyer_data.json", FlyerData)
    pack: ContentPack = run.load("content_pack.json", ContentPack)
    post = next((p for p in pack.posts if p.spec.id == item), None)
    slide = next((sl for sl in pack.screens if sl.spec.id == item), None)
    if post:
        post.copy_ = _write_copy(run, data, [post.spec], extra_note=note)[item]
        _finalise_post(post, data, run.cfg.compliance)
        text = post.caption_final or post.copy_.caption
    elif slide:
        head = _write_screen_heads(run, data, [slide.spec], extra_note=note).get(item)
        if not head:
            raise RuntimeError(f"copy_screens did not return: {item}")
        slide.headline = text = head
    else:
        raise SystemExit(f"no post, story or screen '{item}'")
    run.save("content_pack.json", pack)
    m = run.manifest
    m.state = "GENERATED"
    m.history.append(f"{datetime.now():%Y-%m-%d %H:%M} regen {item}: {note}")
    run.save("manifest.json", m)
    return text


def render(run: Run) -> list[Path]:
    run.require("render")
    from ..adapters.renderer import HtmlRenderer

    cfg = run.cfg
    data: FlyerData = run.load("flyer_data.json", FlyerData)
    pack: ContentPack = run.load("content_pack.json", ContentPack)
    soc, scr = cfg.channels["social"], cfg.channels["screens"]
    base = {"c": cfg.brand["colors"], "accent": data.theme.accent_hex or cfg.brand["colors"]["navy"],
            "logo": (cfg.root / "assets" / "logo-farmagora.png").as_uri(),
            "cover": (run.dir / (data.theme.cover_image_ref or "pages/page-01.png")).as_uri(),
            "flyer_title": data.title, "valid_to": day_month(data.valid_to)}
    out = run.path("out")
    if out.exists():
        shutil.rmtree(out)
    files: list[Path] = []
    with HtmlRenderer(cfg.root / "templates", cfg.root) as r:
        for post in pack.posts:
            s, c = post.spec, post.copy_
            size = tuple(soc["post_size"] if s.kind == "post" else soc["story_size"])
            p = data.product(s.product_ids[0]) if s.product_ids else None
            photo = None
            if p and p.bbox:
                photo = pdfio.crop(run.path("source.pdf"), p.page, p.bbox,
                                   run.path(f"crops/{p.id}.png")).as_uri()
            panel = big_price = until = None
            if s.topic == "service":
                sv = data.service(s.ref_ids[0])
                if sv:
                    panel = " · ".join(sv.items[:4]) or sv.booking
                    big_price = eur_short(sv.price_eur) if sv.price_eur is not None else None
                    until = f"fino al {day_month(sv.valid_to)}" if sv.valid_to else None
                    if sv.booking and not big_price:
                        until = "Prenota " + sv.booking
            if s.topic == "loyalty" and data.loyalty:
                panel = fill("{loyalty}", data) + " con la carta My Agorà"
            if s.topic == "last_call":
                panel = "Sfoglia il volantino su www.farmagora.it o vieni in farmacia"
            if s.topic == "promotion":
                panel = fill("{promo:" + s.ref_ids[0] + "}", data)
            ctx = dict(base, kind=s.kind, topic=s.topic if s.topic != "last_call" else "other",
                       headline=_safe_fill(c.image_headline, data),
                       # product images show the format from the data (code), not an AI subline
                       subline=(p.format or "") if p else _safe_fill(c.image_subline or "", data),
                       product=p, photo=photo, panel=panel, big_price=big_price, until=until, disclaimers=post.disclaimers if s.kind == "post" else post.disclaimers[:1],
                       price=eur(p.price.current_eur) if p else None,
                       old_price=eur(p.price.previous_eur) if p and p.price.previous_eur else None,
                       discount=f"-{p.price.discount_pct}%" if p and p.price.discount_pct else None)
            folder = "social" if s.kind == "post" else "stories"
            post.image_path = str(r.png("post.html.j2", size, ctx, out / folder / f"{s.id}.png").relative_to(run.dir))
            files.append(run.dir / post.image_path)
        for sl in pack.screens:
            p = data.product(sl.spec.product_id)
            photo = (pdfio.crop(run.path("source.pdf"), p.page, p.bbox, run.path(f"crops/{p.id}.png")).as_uri()
                     if p and p.bbox else None)
            ctx = dict(base, headline=sl.headline, product=p, photo=photo, price=sl.price_text, old_price=sl.old_price_text,
                       discount=sl.discount_text, validity=sl.validity_text, disclaimer=sl.disclaimer)
            sl.image_path = str(r.png("screen.html.j2", tuple(scr["size"]), ctx,
                                      out / "screens" / f"{sl.spec.id}.png").relative_to(run.dir))
            files.append(run.dir / sl.image_path)
    for f in out.rglob("*.html"):
        f.unlink()
    _calendar(run, pack, data)
    run.save("content_pack.json", pack)
    run.advance("render", f"{len(files)} images")
    from .review import build_review
    build_review(run)
    return files


def _safe_fill(text: str, data: FlyerData) -> str:
    try:
        return fill(text, data)
    except PlaceholderError:
        return text


def _calendar(run: Run, pack: ContentPack, data: FlyerData) -> Path:
    issues: dict[str, list[str]] = {}
    for i in pack.compliance.issues:
        issues.setdefault(i.target, []).append(f"[{i.severity}] {i.message}")
    p = run.path("out/calendar.csv")
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["data", "canale", "formato", "id", "tema", "caption", "note legali", "immagine", "da verificare"])
        for post in sorted(pack.posts, key=lambda x: (x.spec.publish_date, x.spec.id)):
            caption = post.caption_final + ("\n\n" + " ".join("#" + h.lstrip("#") for h in post.copy_.hashtags)
                                            if post.copy_.hashtags else "")
            w.writerow([post.spec.publish_date.isoformat(), "Instagram/Facebook", post.spec.kind, post.spec.id,
                        post.spec.topic, caption, " ".join(post.disclaimers), post.image_path or "",
                        " | ".join(issues.get(post.spec.id, []))])
    return p


def export(run: Run) -> Path:
    run.require("export")
    pack: ContentPack = run.load("content_pack.json", ContentPack)
    md = ["# Captions\n"]
    for post in pack.posts:
        md.append(f"## {post.spec.id} · {post.spec.publish_date} · {post.spec.kind} · {post.spec.topic}\n")
        md.append(post.caption_final + "\n")
        if post.copy_.hashtags:
            md.append(" ".join("#" + h.lstrip("#") for h in post.copy_.hashtags) + "\n")
        if post.disclaimers:
            md.append("_" + " ".join(post.disclaimers) + "_\n")
    run.path("out/captions.md").write_text("\n".join(md), encoding="utf-8")
    run.save("out/compliance.json", pack.compliance)
    z = run.path(f"export/farmagora-{run.id}.zip")
    z.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(run.path("out").rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(run.path("out")))
    run.advance("export", z.name)
    return z
