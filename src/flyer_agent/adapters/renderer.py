"""HTML -> PNG renderer (Playwright/Chromium). Templates are Jinja2 files designers can edit."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Self

from jinja2 import Environment, FileSystemLoader, select_autoescape


class HtmlRenderer:
    def __init__(self, templates_dir: Path, root: Path):
        self.env = Environment(loader=FileSystemLoader(str(templates_dir)),
                               autoescape=select_autoescape(["html", "j2"]))
        self.root = root
        self._pw = self._browser = None

    def __enter__(self) -> Self:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def html(self, template: str, size: tuple[int, int], ctx: dict[str, Any]) -> str:
        w, h = size
        return self.env.get_template(template).render(w=w, h=h, root=self.root.as_uri(), **ctx)

    def pdf(self, html_file: Path, out: Path) -> Path:
        """Print an HTML page (with its relative images) to an A4 PDF that Drive can preview in the browser."""
        assert self._browser, "use HtmlRenderer as a context manager"
        page = self._browser.new_page()
        page.goto(html_file.as_uri(), wait_until="load")
        page.evaluate("""async () => {  // lazy images never load in print: force and wait for all of them
            const imgs = [...document.images];
            imgs.forEach(i => { i.loading = 'eager'; });
            await Promise.all(imgs.map(i => i.complete ? null : new Promise(r => { i.onload = i.onerror = r; })));
            await document.fonts.ready;
        }""")
        tmp = out.with_name(f".{out.name}.tmp")
        page.pdf(path=str(tmp), format="A4", print_background=True,
                 margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        page.close()
        tmp.replace(out)
        return out

    def png(self, template: str, size: tuple[int, int], ctx: dict[str, Any], out: Path) -> Path:
        assert self._browser, "use HtmlRenderer as a context manager"
        out.parent.mkdir(parents=True, exist_ok=True)
        page = self._browser.new_page(viewport={"width": size[0], "height": size[1]})
        html_file = out.with_suffix(".html")
        html_file.write_text(self.html(template, size, ctx), encoding="utf-8")
        page.goto(html_file.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(out), full_page=False)
        page.close()
        return out
