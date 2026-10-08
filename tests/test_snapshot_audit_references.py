"""Snapshot copies have self-consistent field-level audit history."""

from __future__ import annotations

import json

from thinktui.core import Session
from thinktui.storage import Store


def test_import_remaps_nested_and_before_after_ids_but_not_user_notes(tmp_path):
    store = Store(tmp_path / "audit.db")
    project = store.new_project("Original")
    source_a = Session(project, "premortem", "A")
    source_b = Session(project, "premortem", "B")
    store.save(source_a)
    store.save(source_b)
    linked = Session(
        project, "fmea", "Linked", notes=f"User quoted {source_a.id}", method_state={"source_session_id": source_a.id}
    )
    store.save(linked, "Linked from analysis " + source_a.id)
    linked.method_state["source_session_id"] = source_b.id
    store.save(linked, "Changed source")
    imported = store.import_snapshot(store.snapshot(project))
    copied = {row.title: row for row in store.sessions(imported)}
    events = store.events(copied["Linked"].id)
    before_after = json.loads(events[0]["changes"])
    link = next(row for row in before_after if row["field"] == "method_state.source_session_id")
    assert link["before"] == copied["A"].id
    assert link["after"] == copied["B"].id
    creation = json.loads(events[1]["changes"])
    values = {row["field"]: row["after"] for row in creation}
    assert values["id"] == copied["Linked"].id
    assert values["project_id"] == imported
    assert values["method_state"]["source_session_id"] == copied["A"].id
    assert values["notes"] == f"User quoted {source_a.id}"  # prose isn't a foreign key
    assert events[1]["description"] == "Linked from analysis " + copied["A"].id
    assert source_b.id not in json.dumps([dict(row) for row in events])
    store.close()
