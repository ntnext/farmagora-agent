"""Shared-folder workflow end to end with the offline provider: drop PDF -> rename to approve -> notes -> ready."""

import json
import os
import shutil
from pathlib import Path

import pytest
from openpyxl import load_workbook

from flyer_agent import config
from flyer_agent.adapters import xlsx
from flyer_agent.core import folder_flow as F
from flyer_agent.core import review_sheet as RS
from flyer_agent.stages import watch as W

ROOT = Path(__file__).resolve().parents[2]
FLYER = ROOT / "tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for d in ("config", "prompts", "templates", "assets", "tests/fixtures/flyers"):
        shutil.copytree(ROOT / d, tmp_path / "proj" / d)
    cfg = config.load(tmp_path / "proj", provider="offline")
    monkeypatch.setattr(W, "notify", lambda *a: None)
    folder = tmp_path / "Drive" / "Volantino ottobre"
    folder.mkdir(parents=True)
    pdf = folder / "volantino.pdf"
    shutil.copy(FLYER, pdf)  # fresh mtime, like a file that just arrived
    return cfg, folder, pdf


def _age(p: Path) -> None:
    old = p.stat().st_mtime - 3600
    os.utime(p, (old, old))


def _sheet_edit(path: Path, tab: str, row_id: str, column: str, value: object) -> None:
    """Edit one cell like the approver does in Google Sheets, then age the file past the settle time."""
    wb = load_workbook(path)
    ws = wb[tab]
    head = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "Codice")
    col = next(c for c in range(1, ws.max_column + 1) if ws.cell(head, c).value == column)
    row = next(r for r in range(head + 1, ws.max_row + 1) if ws.cell(r, 1).value == row_id)
    ws.cell(row, col).value = value
    wb.save(path)
    _age(path)


def test_full_folder_round_trip(setup):
    pytest.importorskip("playwright")
    cfg, folder, pdf = setup
    root = folder.parent
    sheet = folder / RS.FILE
    data_dir = folder / F.RESULTS_DIR / F.DATA_DIR
    content = folder / F.RESULTS_DIR / F.CONTENT_DIR

    assert W.process_folder(cfg, folder) == F.Action.WAIT_SYNC  # just copied: may still be syncing
    _age(pdf)
    W.scan(cfg, root)
    assert (folder / F.TODO_DATA).exists() and (data_dir / F.REVIEW_DATA).read_bytes()[:4] == b"%PDF"
    assert sheet.exists()
    agent_made = {p.name for p in folder.iterdir()} - {pdf.name, F.TODO_DATA, F.AGENT_DIR, RS.FILE}
    assert agent_made == {F.RESULTS_DIR}  # every output lives in its own folder
    assert not (content / "Post").exists()  # nothing generated before Gate 1

    W.scan(cfg, root)  # no approval and no edits: nothing happens
    assert W.process_folder(cfg, folder) == F.Action.NOTHING

    # Gate 1 correction from the sheet: unreadable value is reported, valid one applied and re-checked
    run_id = W._load_state(folder)["run_id"]
    first = json.loads((cfg.runs_dir / run_id / "flyer_data.json").read_text())["products"][0]
    _sheet_edit(sheet, RS.TAB_PRODUCTS, first["id"], RS.P_FORMAT, "formato corretto")
    _sheet_edit(sheet, RS.TAB_PRODUCTS, first["id"], RS.P_MY, "forse")
    W.scan(cfg, root)
    todo = (folder / F.TODO_DATA).read_text()
    assert "Correzioni applicate" in todo and "formato corretto" in todo and "NON applicate" in todo
    data = json.loads((cfg.runs_dir / run_id / "flyer_data.json").read_text())
    assert data["products"][0]["format"] == "formato corretto"
    assert "data edits by" in (cfg.runs_dir / run_id / "manifest.json").read_text()  # recorded

    (folder / F.TODO_DATA).rename(folder / "APPROVATO - dati.txt")
    W.scan(cfg, root)
    assert any((content / "Post").glob("post-*.png")) and (folder / F.TODO_PACK).exists()
    assert (content / "Didascalie.md").exists() and (content / "Calendario.csv").exists()
    assert (content / F.REVIEW_PACK).read_bytes()[:4] == b"%PDF"

    # change request from the Contenuti tab
    before = (content / "Post" / "post-03.png").stat().st_mtime_ns
    _sheet_edit(sheet, RS.TAB_CONTENT, "post-03", RS.C_NOTE, "più breve")
    W.scan(cfg, root)
    assert (content / "Post" / "post-03.png").stat().st_mtime_ns != before  # re-rendered after the note
    rows = {r[RS.C_ID]: r for r in xlsx.read(sheet, RS.TAB_CONTENT, RS.CONTENT_HEADERS)}
    assert rows["post-03"][RS.C_NOTE] == "più breve" and "applicata" in rows["post-03"][RS.C_STATUS]
    _age(sheet)
    W.scan(cfg, root)  # the same note is not applied twice
    assert W.process_folder(cfg, folder) == F.Action.NOTHING

    (folder / F.TODO_PACK).rename(folder / "APPROVATO - contenuti.txt")
    W.scan(cfg, root)
    ready = folder / F.RESULTS_DIR / F.READY_DIR
    assert any((ready / "Post").glob("*.png")) and list(ready.glob("*.zip"))
    manifest = (cfg.runs_dir / run_id / "manifest.json").read_text()
    assert '"gate": "data"' in manifest and '"gate": "pack"' in manifest  # both approvals recorded


def test_two_pdfs_ask_for_one(setup):
    cfg, folder, pdf = setup
    shutil.copy2(pdf, folder / "altro.pdf")
    _age(pdf)
    _age(folder / "altro.pdf")
    W.scan(cfg, folder.parent)
    assert "UN solo PDF" in (folder / F.ERROR).read_text()


def test_same_pdf_in_a_new_folder_reuses_the_reading(setup, monkeypatch):
    pytest.importorskip("playwright")
    cfg, folder, pdf = setup
    _age(pdf)
    W.scan(cfg, folder.parent)
    (folder / F.TODO_DATA).rename(folder / "APPROVATO - dati.txt")
    W.scan(cfg, folder.parent)  # Gate 1 passed, content made

    again = folder.parent / "Volantino ottobre (di nuovo)"
    again.mkdir()
    shutil.copy(pdf, again / pdf.name)
    _age(again / pdf.name)
    monkeypatch.setattr(W.P, "extract", lambda run: pytest.fail("the PDF must not be read again"))
    W.process_folder(cfg, again)
    run_id = W._load_state(again)["run_id"]
    assert '"state": "EXTRACTED"' in (cfg.runs_dir / run_id / "manifest.json").read_text()
    assert (again / F.TODO_DATA).exists() and (again / RS.FILE).exists()
