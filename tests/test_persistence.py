import json

from pairwise_prioritizer.comparison_engine import decide, next_pair, skip, undo
from pairwise_prioritizer.models import Outcome
from pairwise_prioritizer.persistence import ProjectStore


def test_partial_round_trip(tmp_path, project):
    store = ProjectStore(tmp_path)
    skip(project, next_pair(project))
    pair = next_pair(project)
    decide(project, pair, Outcome.A_WINS)
    before = next_pair(project)
    store.save(project)
    loaded = store.load(project.id)
    assert next_pair(loaded) == before
    assert loaded.order == project.order
    assert loaded.seed == project.seed
    assert loaded.audit == project.audit
    undo(loaded)
    assert next_pair(loaded) == pair
    store.save(loaded)
    assert store.list_projects()[0].remaining == 6
    assert json.loads(store.path(project.id).read_text())["schema_version"] == 1
    store.delete(project.id)
    assert store.list_projects() == []
