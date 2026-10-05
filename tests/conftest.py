import pytest

from pairwise_prioritizer.comparison_engine import create_project
from pairwise_prioritizer.models import Item


@pytest.fixture
def project():
    return create_project("Test", [Item(name=name) for name in "ABCD"], seed=17)
