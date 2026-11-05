"""Shared-folder workflow (Drive desktop sync, PLAN.md §14): what to do next for one flyer folder. Pure.

The approver works only with files: drop a PDF, rename `DA APPROVARE - …` files to `APPROVATO - …`,
correct data and write change requests in `Revisione.xlsx` (opened in Google Sheets from the browser). This module decides the next step from a snapshot of the folder.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

# User-facing names (Italian).
AGENT_DIR = "_agent"
TODO_DATA = "DA APPROVARE - dati.txt"
TODO_PACK = "DA APPROVARE - contenuti.txt"
NOTES = "NOTE.txt"
ERROR = "ERRORE.txt"
REVIEW_DATA = "Controlla i dati.pdf"
REVIEW_PACK = "Controlla i contenuti.pdf"
# Everything the agent makes goes under RESULTS_DIR, one subfolder per step; the flyer folder itself only holds
# what the approver touches (PDF, DA APPROVARE/APPROVATO files, NOTE.txt, ERRORE.txt).
RESULTS_DIR = "Risultati agente"
DATA_DIR = "1 - Dati letti dal volantino"
CONTENT_DIR = "2 - Contenuti da approvare"
READY_DIR = "3 - Pronto da pubblicare"

SETTLE_SECONDS = 20  # a PDF younger than this may still be syncing
RETRY_AFTER_QUOTA_S = 3600  # provider quota exhausted (429): do not burn requests every scan
RETRY_AFTER_ERROR_S = 300   # other failures (provider busy after its own retries, network)


class Action(str, Enum):
    NOTHING = "nothing"
    WAIT_SYNC = "wait_sync"          # PDF just arrived, may still be uploading
    ONE_PDF_PLEASE = "one_pdf"       # zero or several PDFs
    START = "start"                  # new flyer (or replaced PDF): ingest + extract
    RETRY_EXTRACT = "retry_extract"  # extraction failed before
    EDIT_DATA = "edit_data"          # Prodotti tab of the review spreadsheet changed before Gate 1
    APPROVE_DATA = "approve_data"    # Gate 1 file renamed
    MAKE_CONTENT = "make_content"    # generate + check + render (also resumes an interrupted run)
    APPLY_NOTES = "apply_notes"      # new lines in NOTE.txt
    APPROVE_PACK = "approve_pack"    # Gate 2 file renamed
    EXPORT = "export"


@dataclass(frozen=True)
class FolderSnapshot:
    files: tuple[str, ...]                 # file names in the flyer folder (not recursive)
    pdf_age_s: float = 1e9                 # age of the newest PDF
    pdf_sha: str | None = None             # sha256 of the single PDF, if exactly one
    run_sha: str | None = None             # sha256 of the PDF the current run was made from
    run_state: str | None = None           # manifest state of the current run
    content_blocked: bool = False          # last compliance check had blocking issues
    sheet_changed: bool = False            # review spreadsheet edited (and settled) since the agent last read it
    folder_ready: bool = True              # Gate 1 files were published in this folder for the current run
    new_notes: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def pdfs(self) -> list[str]:
        return [f for f in self.files if f.lower().endswith(".pdf")]


def _key(name: str) -> str:
    t = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z]", "", t)


def approved(files: tuple[str, ...], gate: str) -> bool:
    """True when the approver renamed the gate file: any name starting with 'APPROVATO - dati' / '… contenuti'."""
    target = "approvato" + ("dati" if gate == "data" else "contenuti")
    return any(_key(f).startswith(target) for f in files)


def folder_for_loose_pdf(pdf_name: str, existing: set[str]) -> str:
    """Name of the new flyer folder for a PDF dropped directly in the root (never an existing name)."""
    stem = re.sub(r"\s+", " ", re.sub(r"[_]+", " ", pdf_name.rsplit(".", 1)[0])).strip() or "Volantino"
    name, n = stem, 2
    while name in existing:
        name, n = f"{stem} ({n})", n + 1
    return name


def is_quota_error(error: str) -> bool:
    """True for 'quota exhausted' errors (HTTP 429 / RESOURCE_EXHAUSTED)."""
    return "429" in error or "RESOURCE_EXHAUSTED" in error or "quota" in error.lower()


def retry_delay_s(error: str) -> int:
    """How long to wait before retrying a failed LLM step."""
    return RETRY_AFTER_QUOTA_S if is_quota_error(error) else RETRY_AFTER_ERROR_S


def can_adopt(run_state: str, files: tuple[str, ...]) -> bool:
    """A folder the agent has no memory of (e.g. new working copy) but whose files show the run's progress:
    continue from there instead of starting over (which would cancel the approver's approvals)."""
    if run_state == "EXTRACTED":
        return TODO_DATA in files or approved(files, "data")
    if run_state in {"DATA_APPROVED", "GENERATED", "CHECKED", "RENDERED", "PACK_APPROVED", "EXPORTED"}:
        return approved(files, "data")
    return False


def next_action(s: FolderSnapshot) -> Action:
    """Decide the next step for one flyer folder."""
    pdfs = s.pdfs
    if not pdfs:
        return Action.NOTHING  # empty folder: the approver has not dropped the flyer yet
    if len(pdfs) > 1:
        return Action.ONE_PDF_PLEASE
    if s.pdf_age_s < SETTLE_SECONDS:
        return Action.WAIT_SYNC
    if s.run_state is None or (s.pdf_sha and s.run_sha and s.pdf_sha != s.run_sha):
        return Action.START
    state = s.run_state
    if state == "INGESTED":
        return Action.RETRY_EXTRACT
    if not s.folder_ready:
        return Action.START  # start was interrupted (or the run is reused): set the folder up again
    if state == "EXTRACTED":
        if approved(s.files, "data"):
            return Action.APPROVE_DATA  # pending sheet edits are applied first
        return Action.EDIT_DATA if s.sheet_changed else Action.NOTHING
    if state == "DATA_APPROVED":
        return Action.MAKE_CONTENT
    if state in {"GENERATED", "CHECKED", "RENDERED"}:
        if s.new_notes:
            return Action.APPLY_NOTES
        if state == "GENERATED":  # compliance blocked (wait for notes) or check/render was interrupted
            return Action.NOTHING if s.content_blocked else Action.MAKE_CONTENT
        if state == "CHECKED":
            return Action.MAKE_CONTENT  # render was interrupted
        return Action.APPROVE_PACK if approved(s.files, "pack") else Action.NOTHING
    if state == "PACK_APPROVED":
        return Action.EXPORT
    return Action.NOTHING


# Legacy NOTE.txt lines ("post-03: più breve"); the review spreadsheet is the main way to ask for changes.
NOTE_RE = re.compile(r"^\s*((?:post|story|screen)-\d{2})\s*[:\-–]\s*(.+?)\s*$", re.IGNORECASE)


def note_id(item: str, note: str) -> str:
    return hashlib.sha256(f"{item.lower()}|{note}".encode()).hexdigest()[:16]


def parse_notes(text: str, done: set[str]) -> list[tuple[str, str]]:
    """Lines like 'post-03: più breve' that were not applied yet. Lines starting with '#' are ignored."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = NOTE_RE.match(line)
        if m and note_id(m.group(1), m.group(2)) not in done:
            out.append((m.group(1).lower(), m.group(2)))
    return out
