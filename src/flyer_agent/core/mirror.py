"""Two-way mirror between one online flyer folder (Google Drive) and a local working copy. Pure.

The agent keeps its proven folder workflow (`stages/watch.py`) and runs it on a local copy:

1. pull  - top-level files the approver can change (the PDF, renamed approval files, the review sheet)
           come down when they are new or changed online; files removed or renamed online go away locally.
2. work  - `process_folder` on the local copy, exactly as with a synced folder.
3. push  - everything the agent created, changed or deleted locally goes up (results, sheet, to-do files).

`_agent/` (internal state) stays local. Decisions are made from checksums recorded at the last sync,
so nothing is transferred twice and an online change is never overwritten by a stale local copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LOCAL_ONLY = ("_agent/",)


@dataclass(frozen=True)
class RemoteFile:
    """A file or folder in the online drive (as listed by the CloudFolder port)."""

    id: str
    name: str
    is_folder: bool = False
    md5: str | None = None      # content checksum (None for folders and native Google files)
    modified: float = 0.0       # epoch seconds of the last change online


@dataclass
class Synced:
    id: str
    md5: str


@dataclass
class SyncState:
    files: dict[str, Synced] = field(default_factory=dict)    # relative path -> last synced version
    folders: dict[str, str] = field(default_factory=dict)     # relative folder path -> remote id ("" = flyer folder)

    def to_json(self) -> dict:
        return {"files": {k: {"id": v.id, "md5": v.md5} for k, v in self.files.items()}, "folders": self.folders}

    @classmethod
    def from_json(cls, d: dict) -> SyncState:
        return cls(files={k: Synced(**v) for k, v in (d.get("files") or {}).items()}, folders=d.get("folders") or {})


@dataclass
class PullPlan:
    download: list[RemoteFile] = field(default_factory=list)
    delete_local: list[str] = field(default_factory=list)


@dataclass
class PushPlan:
    upload: list[str] = field(default_factory=list)   # new locally
    update: list[str] = field(default_factory=list)   # changed locally
    trash: list[str] = field(default_factory=list)    # deleted locally


def local_only(path: str) -> bool:
    return path.startswith(LOCAL_ONLY)


def plan_pull(remote_top: list[RemoteFile], local: dict[str, str], state: SyncState) -> PullPlan:
    """What to bring down from the top level of the online folder.

    `local` maps relative paths to md5 of the local copy. Native Google files (no md5) are ignored.
    """
    plan = PullPlan()
    online = {r.name: r for r in remote_top if not r.is_folder and r.md5}
    for name, r in online.items():
        s = state.files.get(name)
        if s is None or s.md5 != r.md5 or s.id != r.id:
            plan.download.append(r)
    for name, s in state.files.items():
        if "/" in name or name in online:
            continue
        if local.get(name) == s.md5:  # removed or renamed online, unchanged here: follow the approver
            plan.delete_local.append(name)
    return plan


def plan_push(local: dict[str, str], state: SyncState) -> PushPlan:
    """What to send up after the agent worked on the local copy."""
    plan = PushPlan()
    for path, md5 in sorted(local.items()):
        if local_only(path):
            continue
        s = state.files.get(path)
        if s is None:
            plan.upload.append(path)
        elif s.md5 != md5:
            plan.update.append(path)
    plan.trash = sorted(p for p in state.files if p not in local and not local_only(p))
    return plan
