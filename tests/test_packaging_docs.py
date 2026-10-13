"""Keep the distributable minimal and the published catalog description accurate."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sdist_excludes_local_audit_notes_and_has_bounded_dependencies():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "/src/**" in include and "/README.md" in include and "/docs/**" in include
    assert not any("AGENTS.md" in path or "specs" in path or "feature.md" in path for path in include)
    dependencies = config["project"]["dependencies"]
    assert any(item.startswith("keyring>=25,") and "<" in item for item in dependencies)
    assert any(item.startswith("platformdirs>=4.0,") and "<" in item for item in dependencies)


def test_catalog_describes_schema_forms_not_json_only():
    text = (ROOT / "docs/methods/catalog.md").read_text(encoding="utf-8")
    assert "schema-driven forms" in text
    assert "optional Advanced JSON" in text
    assert "share the JSON worksheet UI" not in text
