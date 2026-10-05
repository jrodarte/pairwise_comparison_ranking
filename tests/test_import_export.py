import csv
import io
import json

import pytest

from pairwise_prioritizer.comparison_engine import decide
from pairwise_prioritizer.import_export import (
    export_csv,
    export_json,
    export_markdown,
    export_project,
    import_items,
)
from pairwise_prioritizer.models import Outcome
from pairwise_prioritizer.ranking import BradleyTerry


def test_import_text_csv_json(tmp_path):
    text = tmp_path / "items.txt"
    text.write_text(" Alpha \nBeta\n")
    assert [item.name for item in import_items(text)] == ["Alpha", "Beta"]
    csv_file = tmp_path / "items.csv"
    csv_file.write_text("name,title,description\nA,Other,Details\n")
    with pytest.raises(ValueError, match="Choose a CSV column"):
        import_items(csv_file)
    item = import_items(csv_file, "title")[0]
    assert (item.name, item.description) == ("Other", "Details")
    data = tmp_path / "items.json"
    data.write_text(
        json.dumps({"items": ["One", {"name": "Two", "description": "More", "weight": 3}]})
    )
    assert import_items(data)[1].metadata == {"weight": 3}


def test_exports(project, tmp_path):
    a, b = project.order[0]
    decide(project, (a, b), Outcome.TIE)
    results = BradleyTerry().calculate(project.items, list(project.comparisons.values()))
    rows = list(csv.DictReader(io.StringIO(export_csv(results))))
    assert len(rows) == 4
    assert "priority_score" in rows[0]
    data = json.loads(export_json(project, results))
    assert data["comparisons"] and data["audit"] and data["application_version"]
    assert data["results"][0]["rank"] == 1
    assert "Bradley–Terry" in export_markdown(project, results)
    assert "| Rank | Feature |" in export_markdown(project, results)
    for extension in ("csv", "json", "md"):
        path = tmp_path / f"result.{extension}"
        export_project(project, results, path)
        assert path.read_text()
