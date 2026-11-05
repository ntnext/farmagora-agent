"""Command line: one command per stage and gate, plus `run` for the whole flow."""

from __future__ import annotations

import getpass
import webbrowser
from pathlib import Path

import typer

from . import config as config_mod
from .core.models import Issue
from .stages import pipeline as P

app = typer.Typer(help="Farmagorà Flyer-to-Everything agent", no_args_is_help=True, add_completion=False)
STATE: dict = {}

COL = {"blocking": typer.colors.RED, "warning": typer.colors.YELLOW, "review": typer.colors.CYAN}


@app.callback()
def main(provider: str = typer.Option(None, help="Override provider for every task (anthropic, openai, gemini, "
                                                 "openai_compatible, offline)"),
         model: str = typer.Option(None, help="Override model id (with --provider)")) -> None:
    STATE["cfg"] = config_mod.load(provider=provider, model=model)


def _cfg():
    return STATE["cfg"]


def _issues(issues: list[Issue], title: str) -> None:
    counts = {k: sum(i.severity == k for i in issues) for k in COL}
    typer.echo(f"{title}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    for i in issues:
        if i.severity != "review" or len(issues) < 25:
            typer.secho(f"  [{i.severity}] {i.target}: {i.message}", fg=COL[i.severity])


@app.command()
def ingest(pdf: Path) -> None:
    """Create a run from a flyer PDF."""
    run = P.ingest(_cfg(), pdf)
    typer.echo(f"run {run.id} · {run.dir}")


@app.command()
def extract(run: str = typer.Argument(None)) -> None:
    """Read the flyer with the `extract` LLM task and validate the data."""
    r = P.find_run(_cfg(), run)
    data, issues = P.extract(r)
    typer.echo(f"{len(data.products)} products, {len(data.promotions)} promotions, {len(data.services)} services")
    _issues(issues, "validation")
    typer.echo(f"review: {r.path('review.html')}")


@app.command()
def validate(run: str = typer.Argument(None)) -> None:
    """Re-validate flyer_data.json after manual edits."""
    _issues(P.revalidate(P.find_run(_cfg(), run)), "validation")


@app.command("approve-data")
def approve_data(run: str = typer.Argument(None), note: str = "") -> None:
    """Gate 1: approve the extracted data."""
    m = P.approve(P.find_run(_cfg(), run), "data", getpass.getuser(), note)
    typer.secho(f"data approved · {m.state}", fg=typer.colors.GREEN)


@app.command()
def generate(run: str = typer.Argument(None)) -> None:
    """Plan the month and write copy (copy_social + copy_screens tasks)."""
    pack = P.generate(P.find_run(_cfg(), run))
    typer.echo(f"{len(pack.posts)} posts/stories · {len(pack.screens)} screens")


@app.command()
def check(run: str = typer.Argument(None)) -> None:
    """Run the compliance rules."""
    rep = P.check(P.find_run(_cfg(), run))
    _issues(rep.issues, "compliance")
    if rep.blocking:
        typer.secho("blocking issues: fix with `flyer regen --item <id> --note ...` then `flyer check`",
                    fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def render(run: str = typer.Argument(None)) -> None:
    """Render posts, stories and screens to PNG + calendar CSV."""
    r = P.find_run(_cfg(), run)
    files = P.render(r)
    typer.echo(f"{len(files)} images · review: {r.path('review.html')}")


@app.command()
def regen(item: str = typer.Option(..., help="post, story or screen id, e.g. post-03, screen-07"),
          note: str = typer.Option(""), run: str = typer.Argument(None)) -> None:
    """Rewrite one post, story or screen slide with a reviewer note."""
    typer.echo(P.regen(P.find_run(_cfg(), run), item, note))
    typer.echo("now run: flyer check && flyer render")


@app.command("approve-pack")
def approve_pack(run: str = typer.Argument(None), note: str = "") -> None:
    """Gate 2: approve the content pack."""
    m = P.approve(P.find_run(_cfg(), run), "pack", getpass.getuser(), note)
    typer.secho(f"pack approved · {m.state}", fg=typer.colors.GREEN)


@app.command()
def export(run: str = typer.Argument(None)) -> None:
    """Zip everything for manual upload."""
    typer.echo(P.export(P.find_run(_cfg(), run)))


@app.command()
def review(run: str = typer.Argument(None)) -> None:
    """Open review.html."""
    webbrowser.open(P.find_run(_cfg(), run).path("review.html").as_uri())


@app.command()
def status(run: str = typer.Argument(None)) -> None:
    """Show state, history and AI cost of a run."""
    r = P.find_run(_cfg(), run)
    m = r.manifest
    typer.echo(f"run {r.id} · {m.source_name} · {m.state} · AI cost €{m.cost_eur}")
    for h in m.history:
        typer.echo("  " + h)
    for c in m.llm_calls:
        typer.echo(f"  {c.task}: {c.provider}/{c.model} {c.prompt_version} in={c.input_tokens} out={c.output_tokens}"
                   f" {c.latency_s}s")


@app.command("eval")
def eval_cmd(providers: str = typer.Option(..., help="Comma-separated provider[:model], "
                                                    "e.g. gemini:gemini-3.8-flash,anthropic:claude-sonnet-5-5")) -> None:
    """Confronta i provider: estrae ogni volantino con file golden e scrive la scheda di valutazione."""
    from .stages.evaluate import evaluate, golden_flyers
    cfg = _cfg()
    if not golden_flyers(cfg):
        raise SystemExit("nessun file golden trovato in tests/fixtures/flyers/")
    out = evaluate(cfg, [p.strip() for p in providers.split(",") if p.strip()])
    typer.echo(out.read_text(encoding="utf-8"))
    typer.echo(f"scheda salvata: {out}")


@app.command()
def score(run: str = typer.Argument(None)) -> None:
    """Confronta i dati estratti di un run con il file golden dello stesso volantino (nessuna chiamata AI)."""
    from .stages.evaluate import golden_for, score_run
    r = P.find_run(_cfg(), run)
    golden = golden_for(_cfg(), r.manifest.flyer_id)
    if not golden:
        raise SystemExit("nessun file golden per questo volantino")
    s = score_run(r, golden)
    typer.echo(f"Prodotti trovati: {s.matched}/{s.products_golden} (in più: {len(s.extra)})")
    typer.echo(f"Nome + prezzi + badge esatti: {s.core_pct}%  · prezzi {s.pct('prices')}%  · "
               f"tipo prodotto {s.pct('product_type')}%")
    typer.echo(f"Date: {'ok' if s.dates_ok else 'ERRATE'} · promozioni {s.promotions[0]}/{s.promotions[1]} · "
               f"servizi {s.services[0]}/{s.services[1]} · carta My Agorà {'ok' if s.loyalty_ok else 'ERRATA'}")
    for line in s.medicine_errors + s.price_errors + [f"mancante: {m}" for m in s.missing]:
        typer.secho(f"  {line}", fg=typer.colors.RED)
    typer.secho("M1 superato" if s.passed else "M1 non superato",
                fg=typer.colors.GREEN if s.passed else typer.colors.RED)


@app.command()
def watch(folder: str = typer.Option(None, help="Cartella sincronizzata sul Mac; default: drive.watch_dir"),
          drive: bool = typer.Option(None, "--drive/--local",
                                     help="Google Drive online (API, senza app Drive) o cartella locale; "
                                          "default: drive.mode in app.yaml"),
          once: bool = typer.Option(False, "--once", help="Un solo controllo, poi esce"),
          interval: int = typer.Option(30, help="Secondi tra un controllo e l'altro")) -> None:
    """Lavora da una cartella Google Drive: un PDF per sottocartella, risultati nella stessa cartella."""
    from .stages import watch as W
    cfg = _cfg()
    use_api = drive if drive is not None else (cfg.app.get("drive") or {}).get("mode") == "api"
    if use_api and not folder:
        from .stages import drive_sync as D
        gdrive, root_id = D.connect(cfg)
        if once:
            D.scan_drive(cfg, gdrive, root_id, typer.echo)
            return
        try:
            D.watch_drive(cfg, gdrive, root_id, interval, typer.echo)
        except KeyboardInterrupt:
            typer.echo("fermato")
        return
    root = W.watch_root(cfg, folder)
    if once:
        W.scan(cfg, root, typer.echo)
    else:
        try:
            W.watch(cfg, root, interval, typer.echo)
        except KeyboardInterrupt:
            typer.echo("fermato")


@app.command("run")
def run_all(pdf: Path, yes: bool = typer.Option(False, "--yes", help="auto-approve both gates (demo only)")) -> None:
    """Whole flow; stops at each gate unless --yes."""
    cfg = _cfg()
    r = P.ingest(cfg, pdf)
    typer.echo(f"run {r.id}")
    data, issues = P.extract(r)
    _issues(issues, f"extracted {len(data.products)} products")
    if not yes:
        typer.echo(f"Gate 1: check {r.path('review.html')} then `flyer approve-data` and `flyer generate`")
        return
    P.approve(r, "data", getpass.getuser(), "auto (--yes)")
    P.generate(r)
    rep = P.check(r)
    _issues(rep.issues, "compliance")
    if rep.blocking:
        raise typer.Exit(1)
    files = P.render(r)
    typer.echo(f"{len(files)} images")
    P.approve(r, "pack", getpass.getuser(), "auto (--yes)")
    typer.echo(f"export: {P.export(r)}")
    typer.echo(f"review: {r.path('review.html')}")


if __name__ == "__main__":
    app()
