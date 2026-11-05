"""Folder workflow on Google Drive online (API), with an in-memory fake Drive: the approver acts only online."""

import hashlib
import io
import shutil
import time
from pathlib import Path

import pytest
from openpyxl import load_workbook

from flyer_agent import config
from flyer_agent.core import folder_flow as F
from flyer_agent.core import review_sheet as RS
from flyer_agent.core.mirror import RemoteFile
from flyer_agent.stages import drive_sync as D
from flyer_agent.stages import watch as W

ROOT = Path(__file__).resolve().parents[2]
FLYER = ROOT / "tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf"
OLD = time.time() - 3600  # "uploaded an hour ago": past the settle time


class FakeDrive:
    """In-memory CloudFolder: files have parents, names, bytes and a modified time."""

    def __init__(self):
        self.items: dict[str, dict] = {"root": {"name": "", "parent": None, "folder": True, "data": b"", "mod": OLD}}
        self.n = 0
        self.calls: list[str] = []

    def _new(self, parent, name, folder=False, data=b"", mod=None):
        self.n += 1
        fid = f"id{self.n}"
        self.items[fid] = {"name": name, "parent": parent, "folder": folder, "data": data,
                           "mod": time.time() if mod is None else mod, "trashed": False}
        return fid

    def _remote(self, fid):
        it = self.items[fid]
        md5 = None if it["folder"] else hashlib.md5(it["data"], usedforsecurity=False).hexdigest()
        return RemoteFile(fid, it["name"], it["folder"], md5, it["mod"])

    # --- CloudFolder
    def find_folder(self, name):
        return next((k for k, v in self.items.items() if v["folder"] and v["name"] == name and v["parent"] == "root"),
                    None)

    def list_children(self, folder_id):
        return [self._remote(k) for k, v in self.items.items() if v["parent"] == folder_id and not v.get("trashed")]

    def get(self, file_id):
        return self._remote(file_id)

    def download(self, file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.items[file_id]["data"])

    def upload(self, parent_id, name, src):
        self.calls.append(f"upload {name}")
        return self._new(parent_id, name, data=Path(src).read_bytes())

    def update(self, file_id, src):
        self.calls.append(f"update {self.items[file_id]['name']}")
        self.items[file_id].update(data=Path(src).read_bytes(), mod=time.time())

    def create_folder(self, parent_id, name):
        return self._new(parent_id, name, folder=True)

    def move(self, file_id, new_parent_id, old_parent_id):
        self.items[file_id]["parent"] = new_parent_id

    def trash(self, file_id):
        self.items[file_id]["trashed"] = True

    # --- what the approver does in the browser
    def path(self, *names):
        cur = "root"
        for n in names:
            cur = next(k for k, v in self.items.items() if v["parent"] == cur and v["name"] == n and not v.get("trashed"))
        return cur

    def names(self, *names):
        return {v["name"] for v in self.items.values() if v["parent"] == self.path(*names) and not v.get("trashed")}

    def rename(self, fid, name):
        self.items[fid]["name"] = name

    def edit(self, fid, data):
        self.items[fid].update(data=data, mod=OLD + 60)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for d in ("config", "prompts", "templates", "assets", "tests/fixtures/flyers"):
        shutil.copytree(ROOT / d, tmp_path / "proj" / d)
    cfg = config.load(tmp_path / "proj", provider="offline")
    monkeypatch.setattr(W, "notify", lambda *a: None)
    drive = FakeDrive()
    shared = drive._new("root", "Volantini Farmagorà", folder=True, mod=OLD)
    return cfg, drive, shared


def test_whole_flow_online_only(setup):
    pytest.importorskip("playwright")
    cfg, drive, shared = setup
    pdf_id = drive._new(shared, "volantino ottobre.pdf", data=FLYER.read_bytes(), mod=OLD)  # dropped loose

    D.scan_drive(cfg, drive, shared)  # loose PDF gets a folder, is read, Gate 1 files go online
    assert drive.names("Volantini Farmagorà") == {"volantino ottobre"}
    online = drive.names("Volantini Farmagorà", "volantino ottobre")
    assert {"volantino ottobre.pdf", F.TODO_DATA, RS.FILE, F.RESULTS_DIR} <= online
    assert F.AGENT_DIR not in online  # internal state stays local
    assert drive.items[pdf_id]["parent"] == drive.path("Volantini Farmagorà", "volantino ottobre")
    assert F.REVIEW_DATA in drive.names("Volantini Farmagorà", "volantino ottobre", F.RESULTS_DIR, F.DATA_DIR)

    uploads = len(drive.calls)
    D.scan_drive(cfg, drive, shared)  # nothing changed online: nothing transferred
    assert len(drive.calls) == uploads

    folder = ("Volantini Farmagorà", "volantino ottobre")
    drive.rename(drive.path(*folder, F.TODO_DATA), "APPROVATO - dati.txt")  # Gate 1 in the browser
    D.scan_drive(cfg, drive, shared)
    content = drive.names(*folder, F.RESULTS_DIR, F.CONTENT_DIR)
    assert {"Post", "Storie", "Schermi", F.REVIEW_PACK} <= content and F.TODO_PACK in drive.names(*folder)

    # change request typed in the sheet online
    sheet = drive.path(*folder, RS.FILE)
    wb = load_workbook(io.BytesIO(drive.items[sheet]["data"]))
    ws = wb[RS.TAB_CONTENT]
    head = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == RS.C_ID)
    col = next(c for c in range(1, ws.max_column + 1) if ws.cell(head, c).value == RS.C_NOTE)
    row = next(r for r in range(head + 1, ws.max_row + 1) if ws.cell(r, 1).value == "post-03")
    ws.cell(row, col).value = "più breve"
    buf = io.BytesIO()
    wb.save(buf)
    drive.edit(sheet, buf.getvalue())
    D.scan_drive(cfg, drive, shared)
    sheet_now = load_workbook(io.BytesIO(drive.items[drive.path(*folder, RS.FILE)]["data"]))[RS.TAB_CONTENT]
    status = next(sheet_now.cell(r, col + 1).value for r in range(head + 1, sheet_now.max_row + 1)
                  if sheet_now.cell(r, 1).value == "post-03")
    assert "applicata" in status  # the approver sees online that the request was done

    drive.rename(drive.path(*folder, F.TODO_PACK), "APPROVATO - contenuti.txt")  # Gate 2 in the browser
    D.scan_drive(cfg, drive, shared)
    ready = drive.names(*folder, F.RESULTS_DIR, F.READY_DIR)
    assert "Post" in ready and any(n.endswith(".zip") for n in ready)


def test_online_edit_during_work_is_not_overwritten(setup, tmp_path):
    cfg, drive, shared = setup
    folder = drive._new(shared, "Volantino", folder=True, mod=OLD)
    note = drive._new(folder, "ERRORE.txt", data=b"old", mod=OLD)
    D.scan_drive(cfg, drive, shared)  # pulled (no PDF: nothing else happens)
    local = D.drive_settings(cfg)["cache"] / folder / "Volantino" / "ERRORE.txt"
    local.write_text("agent version")  # agent changed it locally...
    drive.edit(note, b"approver version")  # ...while the approver changed it online
    D._push(drive, local.parent, local.parent.parent, D._load(local.parent.parent), print)
    assert drive.items[note]["data"] == b"approver version"


def test_new_working_copy_does_not_duplicate_online_results(setup):
    pytest.importorskip("playwright")
    cfg, drive, shared = setup
    drive._new(shared, "volantino.pdf", data=FLYER.read_bytes(), mod=OLD)
    D.scan_drive(cfg, drive, shared)
    D.reset_cache(cfg)  # e.g. the agent moves to another computer
    D.scan_drive(cfg, drive, shared)
    data_dir = drive.names("Volantini Farmagorà", "volantino", F.RESULTS_DIR, F.DATA_DIR)
    online = [v for v in drive.items.values() if v["name"] == F.REVIEW_DATA and not v.get("trashed")]
    assert data_dir == {F.REVIEW_DATA} and len(online) == 1
