"""Decision table of the shared-folder workflow (pure)."""

from flyer_agent.core.folder_flow import (
    RETRY_AFTER_ERROR_S,
    RETRY_AFTER_QUOTA_S,
    Action,
    FolderSnapshot,
    approved,
    folder_for_loose_pdf,
    next_action,
    note_id,
    parse_notes,
    retry_delay_s,
)

PDF = ("volantino.pdf",)


def snap(**kw) -> FolderSnapshot:
    base = {"files": PDF, "pdf_age_s": 999, "pdf_sha": "a", "run_sha": "a"}
    return FolderSnapshot(**{**base, **kw})


def test_new_and_waiting():
    assert next_action(FolderSnapshot(files=())) == Action.NOTHING
    assert next_action(snap(pdf_age_s=3, run_sha=None)) == Action.WAIT_SYNC
    assert next_action(snap(run_sha=None)) == Action.START
    assert next_action(snap(files=("a.pdf", "b.pdf"))) == Action.ONE_PDF_PLEASE


def test_replaced_pdf_restarts():
    assert next_action(snap(pdf_sha="b", run_state="RENDERED")) == Action.START


def test_gate_1_needs_the_renamed_file():
    assert next_action(snap(run_state="EXTRACTED")) == Action.NOTHING
    files = PDF + ("DA APPROVARE - dati.txt",)
    assert next_action(snap(files=files, run_state="EXTRACTED")) == Action.NOTHING
    files = PDF + ("Approvato - Dati.txt",)
    assert next_action(snap(files=files, run_state="EXTRACTED")) == Action.APPROVE_DATA


def test_content_states():
    assert next_action(snap(run_state="DATA_APPROVED")) == Action.MAKE_CONTENT
    assert next_action(snap(run_state="GENERATED", content_blocked=True)) == Action.NOTHING
    notes = (("post-03", "più breve"),)
    assert next_action(snap(run_state="GENERATED", content_blocked=True, new_notes=notes)) == Action.APPLY_NOTES
    assert next_action(snap(run_state="RENDERED", new_notes=notes)) == Action.APPLY_NOTES
    assert next_action(snap(run_state="RENDERED")) == Action.NOTHING
    files = PDF + ("APPROVATO - contenuti.txt",)
    assert next_action(snap(files=files, run_state="RENDERED")) == Action.APPROVE_PACK
    assert next_action(snap(run_state="PACK_APPROVED")) == Action.EXPORT
    assert next_action(snap(run_state="EXPORTED")) == Action.NOTHING


def test_approval_names_are_tolerant():
    assert approved(("APPROVATO - dati.txt",), "data") and approved(("approvato dati",), "data")
    assert not approved(("DA APPROVARE - dati.txt",), "data")
    assert not approved(("APPROVATO - dati.txt",), "pack")


def test_parse_notes_skips_comments_and_done():
    text = "# post-01: esempio\npost-03: più breve\nstory-02 - togli l'emoji\nciao\n"
    assert parse_notes(text, set()) == [("post-03", "più breve"), ("story-02", "togli l'emoji")]
    assert parse_notes(text, {note_id("post-03", "più breve")}) == [("story-02", "togli l'emoji")]


def test_folder_for_loose_pdf_avoids_existing_names() -> None:
    assert folder_for_loose_pdf("Volantino_maggio.pdf", set()) == "Volantino maggio"
    assert folder_for_loose_pdf("Volantino_maggio.pdf", {"Volantino maggio"}) == "Volantino maggio (2)"


def test_retry_delay_backs_off_longer_on_quota() -> None:
    assert retry_delay_s("429 RESOURCE_EXHAUSTED quota") == RETRY_AFTER_QUOTA_S
    assert retry_delay_s("503 UNAVAILABLE") == RETRY_AFTER_ERROR_S


def test_parse_notes_accepts_screens() -> None:
    assert parse_notes("screen-07: senza la parola cura", set()) == [("screen-07", "senza la parola cura")]


def test_interrupted_start_is_redone() -> None:
    snap = FolderSnapshot(files=("v.pdf",), pdf_sha="a", run_sha="a", run_state="RENDERED", folder_ready=False)
    assert next_action(snap) == Action.START
    assert next_action(FolderSnapshot(files=("v.pdf",), pdf_sha="a", run_sha="a", run_state="INGESTED",
                                      folder_ready=False)) == Action.RETRY_EXTRACT


def test_existing_progress_is_adopted_not_restarted() -> None:
    from flyer_agent.core.folder_flow import can_adopt
    assert can_adopt("EXTRACTED", ("v.pdf", "APPROVATO - dati.txt"))
    assert can_adopt("EXPORTED", ("v.pdf", "APPROVATO - dati.txt", "APPROVATO - contenuti.txt"))
    assert not can_adopt("RENDERED", ("v.pdf",))  # results without approvals: start over
    assert not can_adopt("INGESTED", ("v.pdf", "APPROVATO - dati.txt"))
