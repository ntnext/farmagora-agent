"""PDF adapter (pypdfium2): page renders, text layer, medicine symbols, product photos, cover accent colour."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image, ImageChops


def render_pages(pdf: Path, out_dir: Path, scale: float = 2.0) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    paths = []
    for i in range(len(doc)):
        img = doc[i].render(scale=scale).to_pil().convert("RGB")
        p = out_dir / f"page-{i + 1:02d}.png"
        img.save(p)
        paths.append(p)
    return paths


def text_layer(pdf: Path) -> list[str]:
    doc = pdfium.PdfDocument(str(pdf))
    return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]


PRICE_AT_RE = re.compile(r"€ ?(\d{1,3}(?:\.\d{3})*),(\d{1,2})")
MAX_PAIR_DISTANCE_PT = 200


def _looks_like_medicine_symbol(img: Image.Image) -> bool:
    """Round medicine badge: red cross on a mostly white disc."""
    px = img.convert("RGB").resize((24, 24)).tobytes()
    n = len(px) // 3
    red = sum(1 for i in range(0, len(px), 3) if px[i] > 140 and px[i + 1] < 120 and px[i + 2] < 120) / n
    white = sum(1 for i in range(0, len(px), 3) if min(px[i], px[i + 1], px[i + 2]) > 190) / n
    return red > 0.03 and white > 0.25


def read_price(text: str) -> str | None:
    """Price at the start of `text` ("€12,99 …") as "12,99", or None.

    The price ends at a line break: some flyers print a one-decimal old price ("€12,9") with the discount
    ("24%") on the next line, which must not be read as "12,92". One decimal is padded ("12,9" -> "12,90")
    to match how product prices are written everywhere else.
    """
    m = PRICE_AT_RE.match(text.replace("\r", " ").replace("\n", " "))
    return f"{m.group(1)},{m.group(2).ljust(2, '0')}" if m else None


def _price_boxes(page: pdfium.PdfPage, min_height: float = 4) -> list[tuple[str, float, float]]:
    """Printed prices on the page as (price "13,69", left x, top y) in PDF points; min_height 9 = big prices only."""
    tp = page.get_textpage()
    out = []
    for k in range(tp.count_chars()):
        if tp.get_text_range(k, 1) != "€":
            continue
        price = read_price(tp.get_text_range(k, 12))
        left, bottom, _right, top = tp.get_charbox(k)
        if price and top - bottom >= min_height:
            out.append((price, left, top))
    return out


def medicine_symbols(pdf: Path) -> list[dict]:
    """Find the round medicine symbol on every page and pair it with the card's price.

    Flyer layouts put the symbol either right of the price (small cards) or above it (large cards),
    so a symbol belongs to the nearest price that is to its left or below it, never right or above.
    Returns [{"page": 5, "price": "13,69" | None, "x": .., "y": ..}]; price None = no card nearby (e.g. footer).
    """
    doc = pdfium.PdfDocument(str(pdf))
    found: list[dict] = []
    for i in range(len(doc)):
        page = doc[i]
        prices = _price_boxes(page)
        for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=8):
            left, bottom, right, top = obj.get_bounds()
            if not (10 <= right - left <= 30 and abs((right - left) - (top - bottom)) <= 2):
                continue
            try:
                if not _looks_like_medicine_symbol(obj.get_bitmap(render=False).to_pil()):
                    continue
            except Exception:  # noqa: BLE001, S112 - undecodable image: not a symbol we can read
                continue
            near = [(math.dist((left, top), (px, py)), p) for p, px, py in prices
                    if px <= left + 5 and py <= top + 5]
            near = [n for n in near if n[0] <= MAX_PAIR_DISTANCE_PT]
            price = min(near)[1] if near else None
            found.append({"page": i + 1, "price": price, "x": round(left), "y": round(top)})
    return found


MIN_PHOTO_AREA_PT2 = 1500
MAX_PHOTO_PAGE_SHARE = 0.4  # bigger images are backgrounds / illustrations
PHOTO_MAX_RIGHT_PT = 260    # a card's photo starts within this distance right of its price
PHOTO_MAX_BELOW_PT = 40     # ... and never lies (much) below the price


def product_photos(pdf: Path) -> list[dict]:
    """Pair each large printed price with the nearest product photo of the same card.

    Returns [{"page", "price", "x", "y", "bbox"}] in reading order, bbox = [x0, y0, x1, y1] as 0-1 page fractions
    (origin top-left, as `crop` expects). Each photo and each price is used once (greedy by distance).
    """
    doc = pdfium.PdfDocument(str(pdf))
    found: list[dict] = []
    for i in range(len(doc)):
        page = doc[i]
        w, h = page.get_size()
        prices = _price_boxes(page, min_height=9)
        images = []
        for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=8):
            left, bottom, right, top = obj.get_bounds()
            area = (right - left) * (top - bottom)
            if MIN_PHOTO_AREA_PT2 <= area <= MAX_PHOTO_PAGE_SHARE * w * h:
                images.append((left, bottom, right, top))
        pairs = sorted(
            (math.dist((px, py), (im[0], im[1])), n, k)
            for n, (_p, px, py) in enumerate(prices) for k, im in enumerate(images)
            if im[2] >= px and im[0] <= px + PHOTO_MAX_RIGHT_PT and im[1] >= py - PHOTO_MAX_BELOW_PT - 20
        )
        used_p: set[int] = set()
        used_i: set[int] = set()
        for _d, n, k in pairs:
            if n in used_p or k in used_i:
                continue
            used_p.add(n)
            used_i.add(k)
            left, bottom, right, top = images[k]
            price, px, py = prices[n]
            found.append({"page": i + 1, "price": price, "x": round(px), "y": round(py),
                          "bbox": [round(left / w, 3), round(1 - top / h, 3), round(right / w, 3), round(1 - bottom / h, 3)]})
    return sorted(found, key=lambda f: (f["page"], -f["y"], f["x"]))


def accent_color(cover: Path) -> str:
    """Most frequent saturated colour of the cover (the seasonal theme colour)."""
    im = Image.open(cover).convert("RGB").resize((120, 170))
    counts: Counter[tuple[int, int, int]] = Counter()
    raw = im.tobytes()
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        mx, mn = max(r, g, b), min(r, g, b)
        if mx < 60 or mx - mn < 60:  # skip greys, whites, near-black
            continue
        counts[(r // 16 * 16, g // 16 * 16, b // 16 * 16)] += 1
    if not counts:
        return "#015176"
    r, g, b = counts.most_common(1)[0][0]
    return f"#{r:02X}{g:02X}{b:02X}"


def crop(pdf: Path, page: int, bbox: list[float], out: Path, scale: float = 7.0) -> Path:
    """High-resolution crop of a product photo; bbox = [x0, y0, x1, y1] in 0-1 page coordinates."""
    doc = pdfium.PdfDocument(str(pdf))
    im = doc[page - 1].render(scale=scale).to_pil().convert("RGB")
    w, h = im.size
    x0, y0, x1, y1 = bbox
    c = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
    # trim near-white margins
    diff = ImageChops.difference(c, Image.new("RGB", c.size, (255, 255, 255))).convert("L").point(lambda v: 255 if v > 18 else 0)
    box = diff.getbbox()
    if box:
        c = c.crop(box)
    out.parent.mkdir(parents=True, exist_ok=True)
    c.save(out)
    return out
