"""`flyer watch`: run the pipeline from a shared folder (Google Drive desktop sync), PLAN.md §14.

Layout: <root>/<one folder per flyer>/<flyer.pdf>. The approver drops the PDF, renames the `DA APPROVARE`
files to approve, and corrects data / asks for changes in `Revisione.xlsx` (Google Sheets in the browser).
Results go under `Risultati agente/`.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from ..adapters import xlsx
from ..adapters.notify import notify
from ..config import Config
from ..core import folder_flow as F
from ..core import review_sheet as RS
from ..core.models import ContentPack, FlyerData, Issue
from . import pipeline as P

Log = Callable[[str], None]
OUTPUT_DIRS = {"social": "Post", "stories": "Storie", "screens": "Schermi"}


def watch_root(cfg: Config, folder: str | None) -> Path:
    """The shared root folder: --folder, else `drive.watch_dir` in app.yaml."""
    raw = folder or (cfg.app.get("drive") or {}).get("watch_dir") or ""
    if not raw:
        raise SystemExit("cartella non configurata: usa --folder o imposta drive.watch_dir in config/app.yaml")
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise SystemExit(f"cartella non trovata: {root}")
    return root


def scan(cfg: Config, root: Path, log: Log = print) -> None:
    """One pass over every flyer folder under `root`."""
    _adopt_loose_pdfs(root, log)
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        try:
            process_folder(cfg, folder, log)
        except Exception as e:  # noqa: BLE001 - one broken folder must not stop the others
            _error(folder, f"Errore imprevisto: {e}", log)


def _adopt_loose_pdfs(root: Path, log: Log) -> None:
    """A PDF dropped directly in the root gets its own flyer folder (once it has finished syncing)."""
    for pdf in sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"):
        if time.time() - pdf.stat().st_mtime < F.SETTLE_SECONDS:
            continue
        existing = {p.name for p in root.iterdir()}
        folder = root / F.folder_for_loose_pdf(pdf.name, existing)
        folder.mkdir()
        shutil.move(str(pdf), str(folder / pdf.name))
        log(f"{pdf.name}: spostato nella nuova cartella «{folder.name}»")


def watch(cfg: Config, root: Path, interval_s: int, log: Log = print) -> None:
    """Scan forever (Ctrl+C to stop)."""
    log(f"Controllo la cartella {root} ogni {interval_s} s. Ctrl+C per fermare.")
    while True:
        scan(cfg, root, log)
        time.sleep(interval_s)


# ------------------------------------------------------------------ state
def _state_path(folder: Path) -> Path:
    return folder / F.AGENT_DIR / "state.json"


def _load_state(folder: Path) -> dict:
    p = _state_path(folder)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_state(folder: Path, st: dict) -> None:
    p = _state_path(folder)
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")


def _snapshot(cfg: Config, folder: Path, st: dict) -> tuple[F.FolderSnapshot, P.Run | None]:
    files = tuple(sorted(p.name for p in folder.iterdir() if p.is_file()))
    pdfs = [folder / f for f in files if f.lower().endswith(".pdf")]
    age = min((time.time() - p.stat().st_mtime for p in pdfs), default=1e9)
    sha = hashlib.sha256(pdfs[0].read_bytes()).hexdigest() if len(pdfs) == 1 and age >= F.SETTLE_SECONDS else None
    run = P.Run(cfg, st["run_id"]) if st.get("run_id") and (cfg.runs_dir / st["run_id"]).exists() else None
    run_state = run.manifest.state if run else None
    blocked = False
    if run and run.path("content_pack.json").exists():
        pack = run.load("content_pack.json", ContentPack)
        blocked = bool(pack.compliance and pack.compliance.blocking)
    sheet = folder / RS.FILE
    settled = sheet.exists() and time.time() - sheet.stat().st_mtime >= F.SETTLE_SECONDS
    changed = settled and sheet.stat().st_mtime != st.get("sheet_mtime")
    done = set(st.get("notes_done", []))
    notes: list[tuple[str, str]] = []
    if (folder / F.NOTES).exists():  # legacy text notes still work
        notes += F.parse_notes((folder / F.NOTES).read_text(encoding="utf-8"), done)
    if settled and run_state in {"GENERATED", "CHECKED", "RENDERED"}:
        notes += [(i, n) for i, n in _sheet_notes(folder).items() if F.note_id(i, n) not in done]
    snap = F.FolderSnapshot(files=files, pdf_age_s=age, pdf_sha=sha, run_sha=st.get("pdf_sha"), run_state=run_state,
                            content_blocked=blocked, sheet_changed=changed, new_notes=tuple(notes),
                            folder_ready=bool(run) and st.get("ready_for") == st.get("run_id"))
    return snap, run


def _sheet_notes(folder: Path) -> dict[str, str]:
    """Change requests in the Contenuti tab ({} if the file is unreadable, e.g. still syncing)."""
    try:
        return RS.content_notes(xlsx.read(folder / RS.FILE, RS.TAB_CONTENT, RS.CONTENT_HEADERS))
    except Exception:  # noqa: BLE001 - partial/locked file: try again next scan
        return {}


# ------------------------------------------------------------------ actions
def process_folder(cfg: Config, folder: Path, log: Log = print) -> F.Action:
    """Decide and perform the next step for one flyer folder."""
    st = _load_state(folder)
    snap, run = _snapshot(cfg, folder, st)
    action = F.next_action(snap)
    if action in (F.Action.NOTHING, F.Action.WAIT_SYNC):
        return action
    if action == F.Action.RETRY_EXTRACT and time.time() < st.get("retry_after", 0):
        return F.Action.NOTHING  # backing off after a failure (e.g. daily quota)
    log(f"[{folder.name}] {action.value}")
    if action == F.Action.ONE_PDF_PLEASE:
        _error(folder, "Nella cartella ci deve essere UN solo PDF (il volantino). Togli gli altri.", log)
        return action
    if action == F.Action.START and not st and snap.pdf_sha:
        known = P.Run(cfg, snap.pdf_sha[:12])
        if known.path("manifest.json").exists() and F.can_adopt(known.manifest.state, snap.files):
            st = {"run_id": known.id, "pdf_sha": snap.pdf_sha, "pdf_name": snap.pdfs[0], "notes_done": [],
                  "ready_for": known.id}
            _save_state(folder, st)
            log(f"[{folder.name}] cartella già avviata: riprendo da {known.manifest.state}")
            return F.Action.NOTHING  # the next scan continues from the run's state
    if action == F.Action.START:
        _drop_gate_files(folder, "data", "pack")  # approvals never carry over to a new/replaced PDF
        shutil.rmtree(folder / F.RESULTS_DIR, ignore_errors=True)  # results always match the current PDF
        pdf = folder / snap.pdfs[0]
        run = P.ingest(cfg, pdf)
        st = {"run_id": run.id, "pdf_sha": snap.pdf_sha, "pdf_name": pdf.name, "notes_done": []}
        _save_state(folder, st)
    assert run is not None
    if action == F.Action.START and (reused := P.reopen_for_review(run)):
        log(f"[{folder.name}] volantino già letto: riuso la lettura, si riparte dalla prima approvazione")
        _data_ready(run, folder, st, *reused, log)
    elif action in (F.Action.START, F.Action.RETRY_EXTRACT):
        _extract(run, folder, st, log)
    elif action == F.Action.EDIT_DATA:
        _edit_data(run, folder, st, log)
    elif action == F.Action.APPROVE_DATA:
        if snap.sheet_changed and not _edit_data(run, folder, st, log):
            _refuse_data(run, folder, "le correzioni nel foglio non sono state applicate tutte", log)
            return action
        _approve_data(run, folder, st, log)
    elif action == F.Action.MAKE_CONTENT:
        _make_content(run, folder, st, log)
    elif action == F.Action.APPLY_NOTES:
        _apply_notes(run, folder, st, list(snap.new_notes), log)
    elif action in (F.Action.APPROVE_PACK, F.Action.EXPORT):
        _approve_and_export(run, folder, log)
    return action


def _extract(run: P.Run, folder: Path, st: dict, log: Log) -> None:
    try:
        data, issues = P.extract(run)
    except Exception as e:  # noqa: BLE001 - provider busy, quota...: retried later
        err = str(e)
        delay = F.retry_delay_s(err)
        st["retry_after"] = time.time() + delay
        _save_state(folder, st)
        when = time.strftime("%H:%M", time.localtime(st["retry_after"]))
        why = ("Il servizio di intelligenza artificiale ha finito le richieste gratuite per oggi."
               if F.is_quota_error(err) else "Il servizio di intelligenza artificiale non ha risposto.")
        _error(folder, f"Non sono riuscito a leggere il volantino. {why}\nRiprovo da solo verso le {when}.\n\n"
                       f"Dettaglio: {err[:500]}", log)
        return
    st.pop("retry_after", None)
    _save_state(folder, st)
    _data_ready(run, folder, st, data, issues, log)


def _data_ready(run: P.Run, folder: Path, st: dict, data: FlyerData, issues: list[Issue], log: Log) -> None:
    """Publish what the approver needs for Gate 1."""
    _clear_error(folder)
    _publish_data_review(run, folder)
    _write_sheet(run, folder, st)
    (folder / F.TODO_DATA).write_text(_todo_data_text(data, issues), encoding="utf-8")
    st["ready_for"] = run.id  # this folder is fully set up for this run (an interrupted start is redone)
    _save_state(folder, st)
    blocking = sum(i.severity == "blocking" for i in issues)
    notify("Farmagorà · volantino letto",
           f"{folder.name}: {len(data.products)} prodotti, {blocking} problemi bloccanti. Controlla i dati.")
    log(f"[{folder.name}] dati pronti: {len(data.products)} prodotti, {blocking} bloccanti")


def _edit_data(run: P.Run, folder: Path, st: dict, log: Log) -> bool:
    """Apply corrections from the Prodotti tab. False if some cells could not be applied."""
    try:
        rows = xlsx.read(folder / RS.FILE, RS.TAB_PRODUCTS, RS.PRODUCT_HEADERS)
    except Exception:  # noqa: BLE001 - partial file: next scan
        return False
    edits, issues = P.apply_data_edits(run, rows, f"{getpass.getuser()} (foglio Revisione)")
    _publish_data_review(run, folder)
    # The sheet is NOT rewritten here: the approver may still have it open, and their values must stay visible
    # (including the ones we could not read). We only remember that this version has been read.
    st["sheet_mtime"] = (folder / RS.FILE).stat().st_mtime
    _save_state(folder, st)
    head = []
    if edits.changes:
        head += [f"Correzioni applicate dal foglio ({len(edits.changes)}):", *[f"- {c}" for c in edits.changes], ""]
    if edits.errors:
        head += [f"Correzioni NON applicate ({len(edits.errors)}): sistemale nel foglio", *[f"- {e}" for e in edits.errors],
                 ""]
    (folder / F.TODO_DATA).write_text("\n".join(head) + ("\n" if head else "") + _todo_data_text(edits.data, issues), encoding="utf-8")
    blocking = sum(i.severity == "blocking" for i in issues)
    if edits.changes or edits.errors:
        notify("Farmagorà · correzioni lette",
               f"{folder.name}: {len(edits.changes)} applicate, {len(edits.errors)} da sistemare, {blocking} bloccanti.")
    log(f"[{folder.name}] correzioni dati: {len(edits.changes)} applicate, {len(edits.errors)} errori, "
        f"{blocking} bloccanti")
    return not edits.errors


def _refuse_data(run: P.Run, folder: Path, why: str, log: Log) -> None:
    data = run.load("flyer_data.json", FlyerData)
    issues = [Issue(**i) for i in json.loads(run.path("validation.json").read_text())]
    for f in folder.iterdir():
        if F.approved((f.name,), "data"):
            f.unlink()
    todo = folder / F.TODO_DATA
    body = todo.read_text(encoding="utf-8") if todo.exists() else _todo_data_text(data, issues)
    if body.startswith(REFUSED):
        body = body.split("\n\n", 1)[-1]
    todo.write_text(f"{REFUSED}: {why}.\n\n{body}", encoding="utf-8")
    notify("Farmagorà · approvazione rifiutata", f"{folder.name}: {why}.")
    log(f"[{folder.name}] approvazione dati rifiutata: {why}")


def _approve_data(run: P.Run, folder: Path, st: dict, log: Log) -> None:
    try:
        P.approve(run, "data", f"{getpass.getuser()} (cartella Drive)", "file rinominato in APPROVATO - dati")
    except SystemExit:
        _refuse_data(run, folder, "ci sono ancora problemi bloccanti", log)
        return
    (folder / F.TODO_DATA).unlink(missing_ok=True)
    log(f"[{folder.name}] dati approvati, preparo i contenuti")
    _make_content(run, folder, st, log)


def _make_content(run: P.Run, folder: Path, st: dict, log: Log) -> None:
    try:
        if run.manifest.state == "DATA_APPROVED":
            P.generate(run)
        if run.manifest.state == "GENERATED":
            report = P.check(run)
            if report.blocking:
                _publish_pdf(run, _step_dir(folder, F.CONTENT_DIR) / F.REVIEW_PACK)
                _write_sheet(run, folder, st)
                (folder / F.TODO_PACK).write_text(_blocked_text(report.blocking), encoding="utf-8")
                notify("Farmagorà · contenuti da correggere", f"{folder.name}: {len(report.blocking)} problemi.")
                log(f"[{folder.name}] contenuti bloccati dalla compliance: {len(report.blocking)}")
                return
        P.render(run)
    except Exception as e:  # noqa: BLE001 - provider busy, quota...: retried on the next scan
        _error(folder, "Non sono riuscito a preparare i contenuti. Riprovo al prossimo controllo.\n\n"
                       f"Dettaglio: {str(e)[:500]}", log)
        return
    _clear_error(folder)
    _drop_gate_files(folder, "pack")  # new content must be approved again
    pack = run.load("content_pack.json", ContentPack)
    _publish_content(run, _step_dir(folder, F.CONTENT_DIR, fresh=True), pack)
    _write_sheet(run, folder, st)
    (folder / F.TODO_PACK).write_text(_todo_pack_text(pack), encoding="utf-8")
    notify("Farmagorà · contenuti pronti", f"{folder.name}: {len(pack.posts)} post e storie, {len(pack.screens)} schermi.")
    log(f"[{folder.name}] contenuti pronti: {len(pack.posts)} post/storie, {len(pack.screens)} schermi")


def _apply_notes(run: P.Run, folder: Path, st: dict, notes: list[tuple[str, str]], log: Log) -> None:
    done = set(st.get("notes_done", []))
    for item, note in notes:
        try:
            P.regen(run, item, note)
            log(f"[{folder.name}] {item} riscritto: {note}")
        except SystemExit:
            log(f"[{folder.name}] {item} non esiste: nota ignorata")
        except Exception as e:  # noqa: BLE001 - keep the note for the next scan
            _error(folder, f"Non sono riuscito ad applicare la nota per {item}. Riprovo.\n\nDettaglio: {str(e)[:500]}",
                   log)
            return
        done.add(F.note_id(item, note))
        st["notes_done"] = sorted(done)
        _save_state(folder, st)
    _make_content(run, folder, st, log)


def _approve_and_export(run: P.Run, folder: Path, log: Log) -> None:
    if run.manifest.state == "RENDERED":
        P.approve(run, "pack", f"{getpass.getuser()} (cartella Drive)", "file rinominato in APPROVATO - contenuti")
    zip_path = P.export(run)
    ready = _step_dir(folder, F.READY_DIR, fresh=True)
    pack = run.load("content_pack.json", ContentPack)
    _publish_content(run, ready, pack, with_review=False)
    shutil.copy2(zip_path, ready / f"Farmagora-{folder.name}.zip")
    (folder / F.TODO_PACK).unlink(missing_ok=True)
    notify("Farmagorà · pronto da pubblicare", f"{folder.name}: tutto in '{F.RESULTS_DIR}/{F.READY_DIR}'.")
    log(f"[{folder.name}] esportato in '{F.RESULTS_DIR}/{F.READY_DIR}'")


# ------------------------------------------------------------------ files written for the approver
def _error(folder: Path, text: str, log: Log) -> None:
    p = folder / F.ERROR
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    if old != text:
        p.write_text(text, encoding="utf-8")
        notify("Farmagorà · problema", f"{folder.name}: {text.splitlines()[0]}")
    log(f"[{folder.name}] errore: {text.splitlines()[0]}")


def _drop_gate_files(folder: Path, *gates: str) -> None:
    """Remove approval/to-do files of these gates ('data', 'pack')."""
    todo = {"data": F.TODO_DATA, "pack": F.TODO_PACK}
    for f in list(folder.iterdir()):
        if f.is_file() and any(F.approved((f.name,), g) or f.name == todo[g] for g in gates):
            f.unlink()


def _step_dir(folder: Path, step: str, fresh: bool = False) -> Path:
    """`<flyer folder>/Risultati agente/<step>`; `fresh` empties it first so no stale file survives."""
    d = folder / F.RESULTS_DIR / step
    if fresh:
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clear_error(folder: Path) -> None:
    (folder / F.ERROR).unlink(missing_ok=True)


def _publish_pdf(run: P.Run, out: Path) -> None:
    """The run's review page as a PDF (Drive previews PDFs in the browser; HTML shows as code)."""
    from ..adapters.renderer import HtmlRenderer

    with HtmlRenderer(run.cfg.root / "templates", run.cfg.root) as r:
        r.pdf(run.path("review.html"), out)


def _publish_data_review(run: P.Run, folder: Path) -> None:
    _publish_pdf(run, _step_dir(folder, F.DATA_DIR, fresh=True) / F.REVIEW_DATA)


def _write_sheet(run: P.Run, folder: Path, st: dict) -> None:
    """(Re)write Revisione.xlsx from the run, keeping the approver's change requests, and remember its mtime."""
    path = folder / RS.FILE
    data = run.load("flyer_data.json", FlyerData)
    vpath = run.path("validation.json")
    issues = [Issue(**i) for i in json.loads(vpath.read_text())] if vpath.exists() else []
    before_gate1 = run.manifest.state == "EXTRACTED"
    tabs = [xlsx.Tab(RS.TAB_PRODUCTS, RS.PRODUCT_HEADERS, RS.product_rows(data, issues),
                     RS.P_EDITABLE if before_gate1 else set(),
                     "Correggi le celle gialle se non corrispondono al volantino, poi aspetta un minuto: l'agente "
                     "ricontrolla tutto." if before_gate1 else "Dati approvati: non si modificano più qui.")]
    if run.path("content_pack.json").exists() and not before_gate1:
        notes = _sheet_notes(folder) if path.exists() else {}
        rows = RS.content_rows(run.load("content_pack.json", ContentPack), notes, set(st.get("notes_done", [])),
                               F.note_id)
        intro = ("Per cambiare un testo scrivi cosa vuoi nella colonna gialla (es. 'più breve'). L'agente lo "
                 "riscrive e aggiorna l'immagine.")
    else:
        rows, intro = [], "Si compila dopo l'approvazione dei dati."
    tabs.append(xlsx.Tab(RS.TAB_CONTENT, RS.CONTENT_HEADERS, rows, RS.C_EDITABLE, intro))
    xlsx.write(path, tabs)
    st["sheet_mtime"] = path.stat().st_mtime
    _save_state(folder, st)


def _publish_content(run: P.Run, dest: Path, pack: ContentPack, with_review: bool = True) -> None:
    for src, dst in OUTPUT_DIRS.items():
        target = dest / dst
        target.mkdir(parents=True, exist_ok=True)
        for png in sorted(run.path(f"out/{src}").glob("*.png")):
            shutil.copy2(png, target / png.name)
    if run.path("out/calendar.csv").exists():
        shutil.copy2(run.path("out/calendar.csv"), dest / "Calendario.csv")
    (dest / "Didascalie.md").write_text(_captions_md(pack), encoding="utf-8")
    if with_review:
        _publish_pdf(run, dest / F.REVIEW_PACK)


def _captions_md(pack: ContentPack) -> str:
    out = ["# Didascalie\n"]
    for post in pack.posts:
        out.append(f"## {post.spec.id} · {post.spec.publish_date:%d/%m} · {post.spec.kind} · {post.spec.topic}\n")
        out.append((post.caption_final or post.copy_.caption) + "\n")
        if post.copy_.hashtags:
            out.append(" ".join("#" + h.lstrip("#") for h in post.copy_.hashtags) + "\n")
        if post.disclaimers:
            out.append("_" + " ".join(post.disclaimers) + "_\n")
    return "\n".join(out)


REFUSED = "APPROVAZIONE RIFIUTATA"
SEVERITY_IT = {"blocking": "BLOCCANTE", "warning": "attenzione", "review": "da controllare"}


def _issue_lines(issues: list[Issue]) -> list[str]:
    order = {"blocking": 0, "review": 1, "warning": 2}
    return [f"- [{SEVERITY_IT.get(i.severity, i.severity)}] {i.target}: {i.message}"
            for i in sorted(issues, key=lambda i: order.get(i.severity, 3))]


def _todo_data_text(data: FlyerData, issues: list[Issue]) -> str:
    lines = [f"Volantino: {data.title} · valido dal {data.valid_from:%d/%m/%Y} al {data.valid_to:%d/%m/%Y}",
             f"Letti: {len(data.products)} prodotti, {len(data.promotions)} promozioni, {len(data.services)} servizi",
             "", f"Punti da controllare ({len(issues)}):", *(_issue_lines(issues) or ["- nessuno"]), "",
             "Come procedere:",
             f'1. Apri "{F.RESULTS_DIR}/{F.DATA_DIR}/{F.REVIEW_DATA}" e confronta prezzi, sconti e farmaci',
             "   con il volantino.",
             f'2. Se qualcosa è sbagliato, apri "{RS.FILE}" (scheda {RS.TAB_PRODUCTS}) e correggi le celle gialle.',
             "   L'agente applica le correzioni e ricontrolla tutto entro un minuto; l'esito compare qui.",
             '3. Se è tutto giusto, rinomina questo file in "APPROVATO - dati.txt".',
             "   Con problemi BLOCCANTI l'approvazione viene rifiutata e il file torna com'era."]
    return "\n".join(lines) + "\n"


def _todo_pack_text(pack: ContentPack) -> str:
    review = [i for i in (pack.compliance.issues if pack.compliance else []) if i.severity != "blocking"]
    lines = [(f"Contenuti pronti: {sum(p.spec.kind == 'post' for p in pack.posts)} post, "
              f"{sum(p.spec.kind == 'story' for p in pack.posts)} storie, {len(pack.screens)} schermi."),
             f'Tutto in "{F.RESULTS_DIR}/{F.CONTENT_DIR}": immagini in Post, Storie e Schermi,',
             "testi in Didascalie.md, date in Calendario.csv.", "",
             f"Da controllare a mano ({len(review)}):", *(_issue_lines(review) or ["- nessuno"]), "",
             "Come procedere:",
             f'1. Guarda le immagini e "{F.REVIEW_PACK}".',
             f'2. Per cambiare un testo apri "{RS.FILE}" (scheda {RS.TAB_CONTENT}) e scrivi cosa vuoi nella',
             '   colonna gialla "Modifica richiesta", ad esempio: più breve.',
             "   L'agente lo riscrive e aggiorna l'immagine entro un paio di minuti.",
             '3. Quando va tutto bene, rinomina questo file in "APPROVATO - contenuti.txt".',
             f'   Troverai tutto pronto in "{F.RESULTS_DIR}/{F.READY_DIR}".']
    return "\n".join(lines) + "\n"


def _fix_hint(blocking: list[Issue], item: str) -> str:
    """A ready-to-paste note for one blocked item, based on why it was blocked."""
    msgs = " ".join(i.message for i in blocking if i.target.startswith(item))
    if "forbidden wording" in msgs:
        return "riscrivi senza parole vietate (es. cura, previene, garantito)"
    return "riscrivi senza prezzi o percentuali"


def _blocked_text(blocking: list[Issue]) -> str:
    items = sorted({m.group(0) for i in blocking for m in [re.match(r"(post|story|screen)-\d{2}", i.target)] if m})
    return "\n".join([
        "CONTENUTI DA CORREGGERE: alcuni testi non rispettano le regole.", "",
        *_issue_lines(blocking), "",
        f'Apri "{RS.FILE}" (scheda {RS.TAB_CONTENT}) e nella colonna gialla "Modifica richiesta" scrivi, ad esempio:',
        *[f"- riga {it}: {_fix_hint(blocking, it)}" for it in items],
        "L'agente li riscrive entro un paio di minuti."]) + "\n"
