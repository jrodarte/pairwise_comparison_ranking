import subprocess

import pytest

from pairwise_prioritizer.updater import check_and_pull, find_repo


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def commit(repo, filename, text):
    (repo / filename).write_text(text)
    git(repo, "add", filename)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", filename)


@pytest.fixture
def clones(tmp_path):
    """A bare 'GitHub' remote plus the user's checkout and a second contributor clone."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    local = tmp_path / "local"
    git(tmp_path, "clone", "-q", str(remote), str(local))
    git(local, "checkout", "-qb", "main")
    commit(local, "pyproject.toml", '[project]\nname = "pairwise-prioritizer"\n')
    git(local, "push", "-qu", "origin", "main")
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    return local, other


def test_up_to_date(clones):
    local, _ = clones
    assert find_repo(local) == local
    assert check_and_pull(local).updated is False


def test_pulls_new_commits(clones):
    local, other = clones
    commit(other, "feature.txt", "new")
    git(other, "push", "-q")
    result = check_and_pull(local)
    assert result.updated and "1 update" in result.message
    assert (local / "feature.txt").read_text() == "new"


def test_local_edits_block_pull(clones):
    local, other = clones
    commit(other, "feature.txt", "new")
    git(other, "push", "-q")
    (local / "pyproject.toml").write_text('name = "pairwise-prioritizer"\n# edit\n')
    result = check_and_pull(local)
    assert not result.updated and "local edits" in result.message
    assert not (local / "feature.txt").exists()


def test_ignores_unrelated_repos(tmp_path):
    git(tmp_path, "init", "-q")
    assert find_repo(tmp_path) is None
    assert find_repo(tmp_path.parent / "missing") is None
