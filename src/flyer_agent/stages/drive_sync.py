"""`flyer watch --drive`: the folder workflow on Google Drive online, without the Drive desktop app.

Each scan, for every flyer folder in the shared Drive folder:
pull (approver's changes) -> `watch.process_folder` on a local working copy -> push (agent's results).
The approver only uses Drive in the browser. Planning is pure (`core/mirror.py`); I/O goes through the
CloudFolder port (`adapters/gdrive.py`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from ..config import Config
from ..core import folder_flow as F
from ..core.mirror import RemoteFile, Synced, SyncState, local_only, plan_pull, plan_push
from ..ports.drive import CloudFolder
from . import watch as W

Log = W.Log


def drive_settings(cfg: Config) -> dict:
    d = cfg.app.get("drive") or {}
    return {"folder": d.get("api_folder") or "Volantini Farmagorà",
            "credentials": cfg.root / (d.get("credentials") or "credentials.json"),
            "token": cfg.root / (d.get("token") or ".secrets/google-token.json"),
            "cache": cfg.runs_dir / "drive-cache"}


def connect(cfg: Config) -> tuple[CloudFolder, str]:
    """Sign in (browser the first time) and find the shared folder. Returns (drive, root folder id)."""
    from ..adapters.gdrive import GoogleDrive, credentials

    s = drive_settings(cfg)
    drive = GoogleDrive(credentials(s["credentials"], s["token"]))
    root = drive.find_folder(s["folder"])
    if not root:
        raise SystemExit(f"cartella '{s['folder']}' non trovata in Il mio Drive (drive.api_folder in config/app.yaml)")
    return drive, root


def watch_drive(cfg: Config, drive: CloudFolder, root_id: str, interval_s: int, log: Log = print) -> None:
    """Scan forever (Ctrl+C to stop)."""
    log(f"Controllo la cartella Drive '{drive_settings(cfg)['folder']}' online ogni {interval_s} s. Ctrl+C per fermare.")
    while True:
        try:
            scan_drive(cfg, drive, root_id, log)
        except Exception as e:  # noqa: BLE001 - network or Google hiccup: try again next scan
            log(f"Drive non raggiungibile, riprovo: {str(e)[:200]}")
        time.sleep(interval_s)


def scan_drive(cfg: Config, drive: CloudFolder, root_id: str, log: Log = print) -> None:
    """One pass over the shared folder online."""
    cache = drive_settings(cfg)["cache"]
    children = drive.list_children(root_id)
    children = _adopt_loose_pdfs(drive, root_id, children, log)
    for folder in sorted((c for c in children if c.is_folder and not c.name.startswith((".", "_"))),
                         key=lambda c: c.name):
        try:
            sync_folder(cfg, drive, folder, cache, log)
        except Exception as e:  # noqa: BLE001 - one broken folder must not stop the others
            log(f"[{folder.name}] errore di sincronizzazione: {str(e)[:300]}")


def _adopt_loose_pdfs(drive: CloudFolder, root_id: str, children: list[RemoteFile], log: Log) -> list[RemoteFile]:
    """A PDF dropped directly in the shared folder gets its own flyer folder (once fully uploaded)."""
    for pdf in [c for c in children if not c.is_folder and c.name.lower().endswith(".pdf")]:
        if time.time() - pdf.modified < F.SETTLE_SECONDS:
            continue
        name = F.folder_for_loose_pdf(pdf.name, {c.name for c in children})
        fid = drive.create_folder(root_id, name)
        drive.move(pdf.id, fid, root_id)
        log(f"{pdf.name}: spostato nella nuova cartella «{name}»")
        children = [c for c in children if c.id != pdf.id] + [RemoteFile(id=fid, name=name, is_folder=True)]
    return children


# ------------------------------------------------------------------ one flyer folder
def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest()


def _local_tree(root: Path) -> dict[str, str]:
    """Relative path -> md5 of every local file (temporary dot-files skipped)."""
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): _md5(p) for p in root.rglob("*")
            if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts)}


def _work_dir(cache: Path, folder: RemoteFile) -> Path:
    """`<cache>/<folder id>/<folder name>`; follows a rename done online."""
    base = cache / folder.id
    base.mkdir(parents=True, exist_ok=True)
    for d in base.iterdir():
        if d.is_dir() and d.name != folder.name:
            d.rename(base / folder.name)
    return base / folder.name


def _load(base: Path) -> SyncState:
    p = base / "sync.json"
    return SyncState.from_json(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else SyncState()


def _save(base: Path, state: SyncState) -> None:
    (base / "sync.json").write_text(json.dumps(state.to_json(), indent=1, ensure_ascii=False), encoding="utf-8")


def sync_folder(cfg: Config, drive: CloudFolder, folder: RemoteFile, cache: Path, log: Log = print) -> F.Action:
    """Pull the approver's changes, run the folder workflow locally, push the agent's results."""
    local = _work_dir(cache, folder)
    local.mkdir(exist_ok=True)
    base = local.parent
    state = _load(base)
    state.folders[""] = folder.id

    plan = plan_pull(drive.list_children(folder.id), _local_tree(local), state)
    for r in plan.download:
        dest = local / r.name
        drive.download(r.id, dest)
        os.utime(dest, (r.modified, r.modified))  # settle times follow the online edit time
        state.files[r.name] = Synced(r.id, r.md5 or "")
    for name in plan.delete_local:
        (local / name).unlink(missing_ok=True)
        state.files.pop(name, None)
    _save(base, state)

    action = W.process_folder(cfg, local, log)
    _push(drive, local, base, state, log)
    return action


def _push(drive: CloudFolder, local: Path, base: Path, state: SyncState, log: Log) -> None:
    files = _local_tree(local)
    plan = plan_push(files, state)
    listed: dict[str, dict[str, RemoteFile]] = {}
    for path in plan.upload:
        parent = _ensure_folder(drive, state, path.rpartition("/")[0])
        name = path.rpartition("/")[2]
        if parent not in listed:  # a file with that name may exist online already (e.g. new working copy)
            listed[parent] = {c.name: c for c in drive.list_children(parent) if not c.is_folder}
        same = listed[parent].get(name)
        if same:
            drive.update(same.id, local / path)
            state.files[path] = Synced(same.id, files[path])
        else:
            state.files[path] = Synced(drive.upload(parent, name, local / path), files[path])
        _save(base, state)
    for path in plan.update:
        s = state.files[path]
        if "/" not in path and drive.get(s.id).md5 != s.md5:
            continue  # changed online meanwhile (approver editing): pull it next scan, never overwrite
        drive.update(s.id, local / path)
        state.files[path] = Synced(s.id, files[path])
        _save(base, state)
    for path in plan.trash:
        try:
            drive.trash(state.files[path].id)
        except Exception as e:  # noqa: BLE001 - usually already removed online
            log(f"[{local.name}] {path}: non rimosso online ({str(e)[:80]})")
        state.files.pop(path, None)
        _save(base, state)
    _drop_stale_folders(state, files)
    if plan.upload or plan.update or plan.trash:
        log(f"[{local.name}] Drive aggiornato: {len(plan.upload)} nuovi, {len(plan.update)} modificati, "
            f"{len(plan.trash)} rimossi")


def _ensure_folder(drive: CloudFolder, state: SyncState, rel: str) -> str:
    """Remote id of a relative folder, creating it (and its parents) online if needed."""
    if rel in state.folders:
        return state.folders[rel]
    parent_rel, _, name = rel.rpartition("/")
    parent = _ensure_folder(drive, state, parent_rel)
    existing = next((c for c in drive.list_children(parent) if c.is_folder and c.name == name), None)
    state.folders[rel] = existing.id if existing else drive.create_folder(parent, name)
    return state.folders[rel]


def _drop_stale_folders(state: SyncState, files: dict[str, str]) -> None:
    """Forget folder ids no local file uses any more (they stay online, empty, and are reused by name)."""
    used = {""} | {p.rsplit("/", i)[0] for p in files for i in range(1, p.count("/") + 1)}
    for rel in [r for r in state.folders if r not in used and not local_only(r + "/")]:
        del state.folders[rel]


def reset_cache(cfg: Config) -> None:
    """Forget local working copies (they are rebuilt from Drive on the next scan)."""
    shutil.rmtree(drive_settings(cfg)["cache"], ignore_errors=True)
