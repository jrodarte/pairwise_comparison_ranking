"""Planning fields the spec requires on each form: per-entry tests, status, owners, dates."""

from __future__ import annotations

import pytest
from textual.widgets import Button, Collapsible, DataTable, Input

from thinktui.app import ThinkApp
from thinktui.core import METHODS, Session, assumption_quadrant, assumption_review, assumption_status_label
from thinktui.form_model import schema_for
from thinktui.form_screen import FormScreen
from thinktui.reports import decision_brief, export
from thinktui.safe_widgets import Label, Select, Static
from thinktui.screens import Workspace
from thinktui.snapshot_validation import validate_state
from thinktui.storage import Store
from thinktui.text_field import TextField


def test_assumption_quadrants_follow_the_spec_matrix():
    assert assumption_quadrant(low_confidence=True, high_impact=True) == "TEST FIRST"
    assert assumption_quadrant(low_confidence=False, high_impact=True) == "Important"
    assert assumption_quadrant(low_confidence=True, high_impact=False) == "Monitor"
    assert assumption_quadrant(low_confidence=False, high_impact=False) == "Watch"


def test_key_assumptions_calculates_quadrants_and_checks_planning_fields():
    method = METHODS["assumptions"]
    rows = [
        {"statement": "Sure, minor", "confidence": 90, "impact": 2},
        {"statement": "Unsure, major", "confidence": 20, "impact": 9, "status": "Testing", "change_mind": "SLA miss"},
        {"statement": "Sure, major", "confidence": 80, "impact": 8},
        {"statement": "Unsure, minor", "confidence": 10, "impact": 3},
    ]
    result = method.calculate({"entries": rows})
    assert [row["statement"] for row in result["priorities"]][0] == "Unsure, major"
    assert result["priorities"][0] is rows[1]  # editors map ranked rows back to saved entries
    assert result["quadrants"] == [
        "TEST FIRST: Unsure, major",
        "Monitor: Unsure, minor",
        "Important: Sure, major",
        "Watch: Sure, minor",
    ]
    assert result["review"] == {
        "progress": "0 of 4 tested (1 testing now)",
        "disproved": [],
        "untested_test_first": [],
    }
    assert method.validate({"entries": [{**rows[0], "status": "Maybe"}]})
    assert method.validate({"entries": [{**rows[0], "change_mind": 3}]})
    assert not method.validate({"entries": [{**rows[0], "status": "", "basis": ""}]})


def test_premortem_groups_failure_causes_by_cluster():
    result = METHODS["premortem"].calculate(
        {
            "entries": [
                {"statement": "Vendor folds", "likelihood": 20, "impact": 9, "category": "Market"},
                {"statement": "Key person leaves", "likelihood": 40, "impact": 6, "category": "People"},
                {"statement": "Scope creep", "likelihood": 50, "impact": 4},
            ]
        }
    )
    assert result["clusters"] == {
        "Market": ["Vendor folds"],
        "People": ["Key person leaves"],
        "Unclustered": ["Scope creep"],
    }
    assert METHODS["premortem"].validate({"entries": [{"statement": "x", "likelihood": 1, "impact": 1, "owner": 1}]})


def test_journal_dates_are_checked_against_each_other():
    journal = METHODS["journal"]
    base = {"decision": "Vendor?", "chosen": "Buy"}
    assert not journal.validate({**base, "decision_date": "2026-01-01", "review_date": "2026-06-01"})
    assert "Decision date must be YYYY-MM-DD." in journal.validate({**base, "decision_date": "soon"})
    assert "Review date must be on or after the decision date." in journal.validate(
        {**base, "decision_date": "2026-06-01", "review_date": "2026-01-01"}
    )


def test_snapshots_accept_new_planning_fields_and_reject_bad_status():
    validate_state(
        "journal",
        {"decision": "d", "chosen": "c", "decision_date": "2026-01-01", "context": "x", "assumptions": "y"},
    )
    entry = {"statement": "s", "confidence": 10, "impact": 5, "basis": "b", "change_mind": "c", "status": "Weak"}
    validate_state("assumptions", {"entries": [entry]})
    validate_state("premortem", {"entries": [{"statement": "s", "likelihood": 1, "impact": 1, "owner": "o"}]})
    with pytest.raises(ValueError):
        validate_state("assumptions", {"entries": [{**entry, "status": "Proven"}]})


def test_catalog_forms_carry_missing_planning_fields():
    def keys(method_id: str, group: str) -> list[str]:
        return [child.key for child in next(f for f in schema_for(method_id) if f.key == group).children]

    assert {"basis", "change_mind", "status"} <= set(keys("assumption_mapping", "assumptions"))
    assert "source" in keys("ach", "evidence")
    assert "owner" in keys("risk_matrix", "risks")
    assert "depends_on" in keys("backcasting", "milestones")
    assert {f.key for f in schema_for("reference_class")} >= {"question", "reference_class", "adjusted_estimate"}
    parent = next(c for c in schema_for("hypothesis_tree")[1].children if c.key == "parent_id")
    assert parent.label == "Parent node"
    hypotheses = schema_for("ach")[0]
    assert hypotheses.item_label == "Hypothesis" and hypotheses.children[0].label == "Hypothesis"
    status = next(c for c in schema_for("assumption_mapping")[0].children if c.key == "status")
    assert status.optional and status.label.endswith("(optional)")


def test_assumption_review_counts_test_results_and_flags_what_needs_attention():
    review = assumption_review(
        [
            ("Untested risk", "TEST FIRST", None),
            ("Testing risk", "TEST FIRST", "Testing"),
            ("Held", "Important", "Supported"),
            ("Mixed", "Monitor", "Weak"),
            ("Wrong", "TEST FIRST", "Falsified"),
        ]
    )
    assert review == {
        "progress": "3 of 5 tested (1 held, 1 mixed result, 1 disproved, 1 testing now)",
        "disproved": ["Wrong"],
        "untested_test_first": ["Untested risk"],
    }
    assert assumption_status_label("Supported") == "Held" and assumption_status_label("") == "Not yet tested"
    labels = {c.key: c.label for c in schema_for("assumption_mapping")[0].children}
    assert labels["change_mind"].startswith("Disproved if") and labels["status"].startswith("Test result")


def test_catalog_calculations_report_new_fields_without_inventing_them():
    mapping = METHODS["assumption_mapping"].calculate(
        {
            "assumptions": [
                {"statement": "A", "confidence": 0.2, "impact": 8, "test": "t", "status": None},
                {"statement": "B", "confidence": 0.9, "impact": 8, "test": "t", "status": "Supported"},
            ]
        }
    )
    assert [(row["quadrant"], row["status"]) for row in mapping["priorities"]] == [
        ("TEST FIRST", "Untested"),
        ("Important", "Supported"),
    ]
    assert mapping["review"]["untested_test_first"] == ["A"]
    with pytest.raises(ValueError, match="Status"):
        METHODS["assumption_mapping"].calculate(
            {"assumptions": [{"statement": "A", "confidence": 0.2, "impact": 8, "test": "t", "status": "Sure"}]}
        )
    cases = [{"name": "A", "estimate": 2, "actual": 3}]
    blank = METHODS["reference_class"].calculate({"cases": cases, "inside_estimate": 4, "adjusted_estimate": None})
    assert "your_adjusted_estimate" not in blank
    adjusted = METHODS["reference_class"].calculate({"cases": cases, "inside_estimate": 4, "adjusted_estimate": 5})
    assert adjusted["your_adjusted_estimate"] == 5 and adjusted["outside_view_median"] == 6


def test_method_fields_cover_item_test_results_and_escalation_factors():
    def children(method_id: str, group: str) -> dict:
        return {c.key: c for c in next(f for f in schema_for(method_id) if f.key == group).children}

    item = children("fmea", "failure_modes")["item"]
    assert item.label == "Item / process step (optional)" and item.optional
    result = children("hypothesis_tree", "nodes")["result"]
    assert result.choices == ("Untested", "Supports", "Contradicts", "Inconclusive") and result.show_for == ("test",)
    for group in ("threats", "consequences"):
        factors = children("bow_tie", group)["escalation_factors"]
        assert factors.label == "Escalation factors (optional)" and factors.children[0].label == "Escalation factor"
    assert {f.key: f.label for f in schema_for("root_cause")}["problem"] == "Problem being analysed"
    assert {f.key: f.label for f in schema_for("five_whys")}["problem"] == "Problem being analysed"
    objectives = schema_for("objectives")[0]
    assert (objectives.label, objectives.item_label) == ("Objectives", "Objective")


def test_new_method_fields_are_optional_and_calculated_without_inventing_results():
    row = {k: v for k, v in METHODS["fmea"].example["failure_modes"][0].items() if k != "item"}
    assert METHODS["fmea"].calculate({"failure_modes": [row]})["ranking"][0]["rpn"] == 216  # older rows still work
    with_item = METHODS["fmea"].calculate({"failure_modes": [{**row, "item": "Checkout"}]})
    assert with_item["ranking"][0]["item"] == "Checkout"
    with pytest.raises(ValueError, match="Item"):
        METHODS["fmea"].calculate({"failure_modes": [{**row, "item": 3}]})

    nodes = [
        {"id": "h", "parent_id": None, "label": "Cache", "kind": "hypothesis"},
        {"id": "t1", "parent_id": "h", "label": "Trace", "kind": "test", "result": "Contradicts"},
        {"id": "t2", "parent_id": "h", "label": "Load test", "kind": "test"},
        {"id": "t3", "parent_id": "h", "label": "Logs", "kind": "test", "result": None},
    ]
    tree = METHODS["hypothesis_tree"].calculate({"question": "Why slow?", "nodes": nodes})
    assert tree["test_results"] == {"Cache": {"Untested": 2, "Supports": 0, "Contradicts": 1, "Inconclusive": 0}}
    assert tree["untested"] == ["Trace", "Load test", "Logs"][1:]
    assert tree["hypotheses"][0]["children"][0]["result"] == "Contradicts"
    # A result left on a node later changed to a hypothesis is kept but not counted.
    stale = [{**nodes[0], "result": "Supports"}, nodes[1]]
    assert (
        METHODS["hypothesis_tree"].calculate({"question": "Why?", "nodes": stale})["test_results"]["Cache"]["Supports"]
        == 0
    )
    with pytest.raises(ValueError, match="Test result"):
        METHODS["hypothesis_tree"].calculate({"question": "Why?", "nodes": [nodes[0], {**nodes[1], "result": "Yes"}]})

    bow = {
        "hazard": "API",
        "top_event": "Down",
        "threats": [{"name": "Outage", "preventive_controls": ["Fallback"], "escalation_factors": ["Same region"]}],
        "consequences": [{"name": "Lost requests", "mitigating_controls": ["Queue"]}],
    }
    assert METHODS["bow_tie"].calculate(bow)["without_escalation_factors"] == ["Lost requests"]
    with pytest.raises(ValueError, match="Escalation"):
        METHODS["bow_tie"].calculate({**bow, "threats": [{**bow["threats"][0], "escalation_factors": [" "]}]})
    validate_state("bow_tie", bow)
    validate_state("hypothesis_tree", {"question": "Why?", "nodes": nodes})


@pytest.mark.asyncio
async def test_hypothesis_tree_shows_test_result_only_for_tests(tmp_path):
    store = Store(tmp_path / "tree.db")
    nodes = [
        {"id": "h", "parent_id": None, "label": "Cache", "kind": "hypothesis"},
        {"id": "t", "parent_id": "h", "label": "Trace", "kind": "test"},
    ]
    session = Session(store.new_project("Plan"), "hypothesis_tree", "Slow", method_state={"nodes": nodes})
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen(FormScreen(session))
        await pilot.pause()
        screen = app.screen
        results = [path for path, field in screen.fields.values() if field.key == "result"]
        assert results == [("nodes", 1, "result")]
        kind = next(i for i, (p, _) in screen.fields.items() if p == ("nodes", 0, "kind"))
        screen.query_one(f"#{kind}", Select).value = "test"
        await pilot.pause()
        results = [path for path, field in screen.fields.values() if field.key == "result"]
        assert results == [("nodes", 0, "result"), ("nodes", 1, "result")]
    store.close()


@pytest.mark.asyncio
async def test_key_assumptions_editor_new_edit_cancel_and_per_entry_change_mind(tmp_path):
    store = Store(tmp_path / "kac.db")
    session = Session(store.new_project("Plan"), "assumptions", "Check")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 60)) as pilot:
        app.open_session(session)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Workspace)
        assert str(screen.query_one("#new-entry", Button).label) == "+ New assumption"
        assert screen.query_one("#cancel-edit", Button).disabled
        screen.query_one("#entry", TextField).value = "Vendor API holds load"
        screen.query_one("#entry-basis", TextField).value = "Load test last year"
        screen.query_one("#confidence", Input).value = "30"
        screen.query_one("#impact", Input).value = "9"
        screen.query_one("#action", TextField).value = "Run a 2x load test"
        screen.query_one("#entry-change_mind", TextField).value = "p99 latency above 400 ms"
        screen.query_one("#entry-status", Select).value = "Testing"
        await pilot.pause()
        assert "TEST FIRST" in str(screen.query_one("#dedicated-feedback", Static).render())
        screen.query_one("#add", Button).press()
        await pilot.pause()
        saved = store.load(session.id).method_state["entries"][0]
        assert saved["change_mind"] == "p99 latency above 400 ms"
        assert saved["basis"] == "Load test last year"
        assert saved["status"] == "Testing"
        assert screen.query_one("#entry", TextField).value == ""  # ready for the next entry
        table = screen.query_one("#entry-list", DataTable)
        assert "TEST FIRST" in str(table.get_row_at(0)) and "Testing" in str(table.get_row_at(0))

        # Enter on a ranked row loads it for editing; Cancel leaves the saved row unchanged.
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert screen.query_one("#entry-change_mind", TextField).value == "p99 latency above 400 ms"
        assert "Editing" in str(screen.query_one("#entry-mode", Label).render())
        assert not screen.query_one("#cancel-edit", Button).disabled
        screen.query_one("#entry", TextField).value = "Discarded edit"
        screen.query_one("#cancel-edit", Button).press()
        await pilot.pause()
        assert store.load(session.id).method_state["entries"][0]["statement"] == "Vendor API holds load"
        assert "New assumption" in str(screen.query_one("#entry-mode", Label).render())

        # Editing preserves keys the editor does not show and updates status in place.
        entries = store.load(session.id).method_state["entries"]
        entries[0]["evidence_ids"] = ["e1"]
        session = store.load(session.id)
        session.method_state["entries"] = entries
        store.save(session)
        app.open_session(store.load(session.id))
        await pilot.pause()
        screen = app.screen
        screen.query_one("#edit-entry", Button).press()
        await pilot.pause()
        screen.query_one("#entry-status", Select).value = "Falsified"
        await pilot.pause()
        screen.query_one("#add", Button).press()
        await pilot.pause()
        saved = store.load(session.id).method_state["entries"]
        assert len(saved) == 1 and saved[0]["status"] == "Falsified" and saved[0]["evidence_ids"] == ["e1"]
        results = str(screen.query_one("#results", Static).content)
        assert "Tests: 1 of 1 tested (1 disproved)" in results
        assert "Disproved — revisit the plan:" in results
        assert "Disproved if: p99 latency above 400 ms" in results

        # + New starts a blank entry from the keyboard too.
        screen.query_one("#entry", TextField).value = "half-typed"
        screen.query_one("#entry-list", DataTable).focus()
        await pilot.press("plus")
        await pilot.pause()
        assert screen.query_one("#entry", TextField).value == ""
        assert screen.query_one("#entry", TextField).has_focus
    destination = tmp_path / "kac.md"
    export(store.load(session.id), destination)
    text = destination.read_text()
    assert "p99 latency above 400 ms" in text and "Falsified" in text and "TEST FIRST" in text
    store.close()


@pytest.mark.asyncio
async def test_premortem_editor_saves_cluster_owner_and_warning_sign(tmp_path):
    store = Store(tmp_path / "premortem.db")
    session = Session(store.new_project("Plan"), "premortem", "Launch")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 60)) as pilot:
        app.open_session(session)
        await pilot.pause()
        screen = app.screen
        assert str(screen.query_one("#new-entry", Button).label) == "+ New failure mode"
        assert not screen.query("#entry-status")
        screen.query_one("#entry", TextField).value = "Vendor misses the deadline"
        screen.query_one("#entry-category", TextField).value = "Suppliers"
        screen.query_one("#confidence", Input).value = "40"
        screen.query_one("#impact", Input).value = "8"
        screen.query_one("#action", TextField).value = "Weekly vendor check-in"
        screen.query_one("#entry-owner", TextField).value = "Delivery lead"
        screen.query_one("#entry-warning_sign", TextField).value = "Two slipped milestones"
        screen.query_one("#add", Button).press()
        await pilot.pause()
        row = store.load(session.id).method_state["entries"][0]
        assert (row["category"], row["owner"], row["warning_sign"]) == (
            "Suppliers",
            "Delivery lead",
            "Two slipped milestones",
        )
        app.open_session(store.load(session.id))
        await pilot.pause()
        cells = str(app.screen.query_one("#entry-list", DataTable).get_row_at(0))
        assert "Suppliers" in cells and "Delivery lead" in cells
        assert "Warning sign: Two slipped milestones" in str(app.screen.query_one("#results", Static).render())
    assert "Suppliers" in decision_brief(store.load(session.id))
    store.close()


@pytest.mark.asyncio
async def test_journal_records_date_context_and_assumptions_separately(tmp_path):
    store = Store(tmp_path / "journal.db")
    session = Session(store.new_project("Plan"), "journal", "Vendor")
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 60)) as pilot:
        app.open_session(session)
        await pilot.pause()
        for key, value in {
            "decision": "Build or buy?",
            "decision_date": "2026-10-01",
            "context": "Contract renewal",
            "chosen": "Buy",
            "assumptions": "Vendor stays solvent",
            "risks": "Lock-in",
        }.items():
            app.screen.query_one(f"#journal-{key}").value = value
        app.screen.query_one("#journal-save", Button).press()
        await pilot.pause()
        state = store.load(session.id).method_state
        assert (state["decision_date"], state["context"], state["assumptions"], state["risks"]) == (
            "2026-10-01",
            "Contract renewal",
            "Vendor stays solvent",
            "Lock-in",
        )
        validate_state("journal", state)
    store.close()


@pytest.mark.asyncio
async def test_schema_form_uses_plus_add_buttons_item_headings_and_overall_change_mind(tmp_path):
    store = Store(tmp_path / "form.db")
    session = Session(
        store.new_project("Plan"),
        "scenarios",
        "Futures",
        method_state={"axes": [{"name": "Demand", "low": "Flat demand", "high": "Boom"}, {"name": "Rules"}]},
    )
    store.save(session)
    app = ThinkApp(store=store)
    async with app.run_test(size=(120, 60)) as pilot:
        app.switch_screen(FormScreen(session))
        await pilot.pause()
        screen = app.screen
        labels = [str(label.render()) for label in screen.query(Label)]
        assert "+ Add driving force" in [str(button.label) for button in screen.query(Button)]
        assert "Scenario · Flat demand × Rules high" in labels
        assert "Axis 1 · Demand" in [str(row.title) for row in screen.query(Collapsible)]
        sections = [str(section.title) for section in screen.query(Collapsible).filter(".form-section")]
        assert sections[-1] == "Overall: what would change your mind? (optional)"  # after the scenarios
        assert sections.index("Scenarios") < len(sections) - 1
    store.close()
