"""Run state machine. Pure."""

from __future__ import annotations

ORDER = ["INGESTED", "EXTRACTED", "DATA_APPROVED", "GENERATED", "CHECKED", "RENDERED", "PACK_APPROVED", "EXPORTED"]

# stage -> state required BEFORE it can run (minimum), state AFTER it ran
REQUIRES = {
    "extract": "INGESTED",
    "validate": "EXTRACTED",
    "approve-data": "EXTRACTED",
    "generate": "DATA_APPROVED",
    "check": "GENERATED",
    "render": "CHECKED",
    "approve-pack": "RENDERED",
    "export": "PACK_APPROVED",
}
PRODUCES = {
    "extract": "EXTRACTED",
    "approve-data": "DATA_APPROVED",
    "generate": "GENERATED",
    "check": "CHECKED",
    "render": "RENDERED",
    "approve-pack": "PACK_APPROVED",
    "export": "EXPORTED",
}


class StateError(RuntimeError):
    pass


def can_run(stage: str, state: str) -> bool:
    need = REQUIRES.get(stage)
    return need is None or ORDER.index(state) >= ORDER.index(need)


def next_state(stage: str, state: str) -> str:
    """Re-running an earlier stage moves the run back (later approvals become invalid)."""
    if not can_run(stage, state):
        raise StateError(f"'{stage}' needs state {REQUIRES[stage]} or later; run is {state}")
    return PRODUCES.get(stage, state)
