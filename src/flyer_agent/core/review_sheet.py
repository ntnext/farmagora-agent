"""The review spreadsheet (`Revisione.xlsx`) the approver edits in Google Sheets from the browser. Pure.

Two tabs:
- `Prodotti`: one row per product. Before Gate 1 the approver can correct name, format, prices, discount,
  medicine and My Agorà flags; the agent applies the changes and re-runs every data check.
- `Contenuti`: one row per post, story and screen slide, with a "Modifica richiesta" column for change requests.

This module only builds rows and interprets edited rows; reading/writing the file is in `adapters/xlsx.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import ContentPack, FlyerData, Issue, Product

FILE = "Revisione.xlsx"
TAB_PRODUCTS = "Prodotti"
TAB_CONTENT = "Contenuti"

# Product columns; the ones in P_EDITABLE can be changed by the approver before Gate 1.
P_ID, P_PAGE, P_NAME, P_FORMAT = "Codice", "Pagina", "Nome", "Formato"
P_PRICE, P_OLD, P_DISC, P_MED, P_MY = "Prezzo", "Prezzo barrato", "Sconto %", "Farmaco", "Solo My Agorà"
P_CHECK = "Da controllare"
PRODUCT_HEADERS = [P_ID, P_PAGE, P_NAME, P_FORMAT, P_PRICE, P_OLD, P_DISC, P_MED, P_MY, P_CHECK]
P_EDITABLE = {P_NAME, P_FORMAT, P_PRICE, P_OLD, P_DISC, P_MED, P_MY}

C_ID, C_KIND, C_DATE, C_TEXT, C_NOTE, C_STATUS = "Codice", "Tipo", "Data", "Testo", "Modifica richiesta", "Stato"
CONTENT_HEADERS = [C_ID, C_KIND, C_DATE, C_TEXT, C_NOTE, C_STATUS]
C_EDITABLE = {C_NOTE}

KIND_IT = {"post": "post", "story": "storia", "screen": "schermo"}
YES = {"si", "sì", "s", "x", "yes", "y", "true", "vero", "1"}
NO = {"", "no", "n", "false", "falso", "0", "-"}


def _yn(v: bool) -> str:
    return "sì" if v else "no"


def _num(v: Decimal | None) -> str:
    return "" if v is None else f"{v:.2f}".replace(".", ",")


def product_rows(data: FlyerData, issues: list[Issue]) -> list[list[Any]]:
    """Rows of the Prodotti tab (same order as the flyer)."""
    by_product: dict[str, list[str]] = {}
    for i in issues:
        if i.target.startswith("product:"):
            by_product.setdefault(i.target.split(":", 1)[1], []).append(i.message)
    return [[p.id, p.page, p.name, p.format or "", _num(p.price.current_eur), _num(p.price.previous_eur),
             p.price.discount_pct if p.price.discount_pct is not None else "", _yn(p.is_medicine),
             _yn(p.my_agora_only), "; ".join(by_product.get(p.id, []) + p.review_notes)]
            for p in data.products]


def content_rows(pack: ContentPack, notes: dict[str, str], done: set[str], note_key: Any) -> list[list[Any]]:
    """Rows of the Contenuti tab. `notes` keeps the approver's requests; `done` marks the ones applied."""
    rows: list[list[Any]] = []
    for post in pack.posts:
        s = post.spec
        rows.append([s.id, KIND_IT.get(s.kind, s.kind), f"{s.publish_date:%d/%m/%Y}",
                     post.caption_final or post.copy_.caption, *_note_cells(s.id, notes, done, note_key)])
    for sl in pack.screens:
        rows.append([sl.spec.id, KIND_IT["screen"], "", sl.headline, *_note_cells(sl.spec.id, notes, done, note_key)])
    return rows


def _note_cells(item: str, notes: dict[str, str], done: set[str], note_key: Any) -> list[str]:
    note = notes.get(item, "")
    if not note:
        return ["", ""]
    return [note, "✓ applicata" if note_key(item, note) in done else "in attesa"]


def content_notes(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Change requests written in the Contenuti tab: {item id: note}."""
    out = {}
    for r in rows:
        item, note = str(r.get(C_ID) or "").strip().lower(), str(r.get(C_NOTE) or "").strip()
        if item and note:
            out[item] = note
    return out


# ------------------------------------------------------------------ applying product edits
@dataclass
class DataEdits:
    data: FlyerData
    changes: list[str] = field(default_factory=list)  # human-readable, Italian ("post-03: prezzo 9,69 → 9,49")
    errors: list[str] = field(default_factory=list)   # cells that could not be read

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def parse_eur(v: Any) -> Decimal | None:
    """'9,69', '9.69', '€ 9,69', 9.69 -> Decimal('9.69'); '' -> None. Raises ValueError if unreadable."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, int | float | Decimal):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    t = re.sub(r"[€\s]", "", str(v))
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t).quantize(Decimal("0.01"))
    except InvalidOperation as e:
        raise ValueError(f"prezzo non valido: {v!r}") from e


def parse_pct(v: Any) -> int | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    t = str(v).strip().lstrip("-").rstrip("%").strip().replace(",", ".")
    try:
        f = float(t)
    except ValueError as e:
        raise ValueError(f"sconto non valido: {v!r}") from e
    return round(f * 100) if 0 < f < 1 and "." in t else round(f)  # Sheets may turn "25%" into 0.25


def parse_yn(v: Any) -> bool:
    t = str(v if v is not None else "").strip().casefold()
    if t in YES:
        return True
    if t in NO:
        return False
    raise ValueError(f"scrivi sì o no, non {v!r}")


def _price_required(v: Any) -> Decimal:
    d = parse_eur(v)
    if d is None:
        raise ValueError("il prezzo non può essere vuoto")
    return d


# (column, label for messages, parser, attribute path)
_FIELDS: list[tuple[str, str, Any, str]] = [
    (P_NAME, "nome", lambda v: str(v or "").strip() or None, "name"),
    (P_FORMAT, "formato", lambda v: str(v or "").strip() or None, "format"),
    (P_PRICE, "prezzo", _price_required, "price.current_eur"),
    (P_OLD, "prezzo barrato", parse_eur, "price.previous_eur"),
    (P_DISC, "sconto", parse_pct, "price.discount_pct"),
    (P_MED, "farmaco", parse_yn, "is_medicine"),
    (P_MY, "solo My Agorà", parse_yn, "my_agora_only"),
]


def apply_product_rows(data: FlyerData, rows: list[dict[str, Any]]) -> DataEdits:
    """Apply the approver's corrections from the Prodotti tab, cell by cell. Unreadable cells are reported and
    left unchanged; the other cells of the same row are still applied."""
    out = DataEdits(data=data.model_copy(deep=True))
    products = {p.id: p for p in out.data.products}
    for r in rows:
        pid = str(r.get(P_ID) or "").strip()
        if not pid:
            continue
        p = products.get(pid)
        if p is None:
            out.errors.append(f"{pid}: codice prodotto sconosciuto (non cambiare la colonna {P_ID})")
            continue
        for column, label, parse, attr in _FIELDS:
            if column not in r:
                continue
            try:
                value = parse(r[column])
            except ValueError as e:
                out.errors.append(f"{p.name}, {label}: {e}")
                continue
            if attr == "name" and value is None:
                out.errors.append(f"{p.name}, nome: non può essere vuoto")
                continue
            obj, _, name = attr.rpartition(".")
            _set(out, p, label, p.price if obj == "price" else p, name, value)
    return out


def _show(v: Any) -> str:
    if isinstance(v, bool):
        return _yn(v)
    if isinstance(v, Decimal):
        return _num(v)
    return "vuoto" if v in (None, "") else str(v)


def _set(out: DataEdits, p: Product, label: str, obj: Any, attr: str, new: Any) -> None:
    old = getattr(obj, attr)
    if old != new:
        setattr(obj, attr, new)
        if label == "farmaco":  # keep the type consistent with the flag (validation checks both)
            if new:
                p.product_type = "farmaco"
            elif p.product_type == "farmaco":
                p.product_type = "altro"
        p.review_notes = [*p.review_notes, f"corretto a mano: {label}"]
        out.changes.append(f"{p.name}: {label} {_show(old)} → {_show(new)}")
