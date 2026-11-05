"""Drive mirror planning (pure): what comes down, what goes up, nothing overwritten by mistake."""

from flyer_agent.core.mirror import RemoteFile, Synced, SyncState, plan_pull, plan_push


def test_new_and_changed_online_files_are_downloaded():
    state = SyncState(files={"volantino.pdf": Synced("p1", "aaa")})
    remote = [RemoteFile("p1", "volantino.pdf", md5="aaa"), RemoteFile("x1", "Revisione.xlsx", md5="new"),
              RemoteFile("d1", "Risultati agente", is_folder=True), RemoteFile("g1", "Appunti", md5=None)]
    plan = plan_pull(remote, {"volantino.pdf": "aaa"}, state)
    assert [r.name for r in plan.download] == ["Revisione.xlsx"]  # folders and native Google files ignored


def test_rename_online_replaces_the_local_file():
    state = SyncState(files={"DA APPROVARE - dati.txt": Synced("t1", "m1")})
    remote = [RemoteFile("t1", "APPROVATO - dati.txt", md5="m1")]
    plan = plan_pull(remote, {"DA APPROVARE - dati.txt": "m1"}, state)
    assert [r.name for r in plan.download] == ["APPROVATO - dati.txt"]
    assert plan.delete_local == ["DA APPROVARE - dati.txt"]


def test_file_deleted_online_but_changed_locally_is_kept():
    state = SyncState(files={"ERRORE.txt": Synced("e1", "old")})
    assert plan_pull([], {"ERRORE.txt": "newer"}, state).delete_local == []


def test_push_uploads_new_updates_changed_trashes_deleted_and_keeps_agent_state_local():
    state = SyncState(files={"a.txt": Synced("1", "m"), "b.txt": Synced("2", "m"), "gone.txt": Synced("3", "m")})
    local = {"a.txt": "m", "b.txt": "changed", "Risultati agente/x.png": "p", "_agent/state.json": "s"}
    plan = plan_push(local, state)
    assert plan.upload == ["Risultati agente/x.png"] and plan.update == ["b.txt"] and plan.trash == ["gone.txt"]


def test_state_round_trip():
    s = SyncState(files={"a": Synced("1", "m")}, folders={"": "root", "R": "r"})
    assert SyncState.from_json(s.to_json()) == s
