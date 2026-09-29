import pytest

from harness.actions import FactsQuery
from harness.environment import LocalEnvironment
from harness.public_tree import TreeError, capture_public_tree
from harness.tests.helpers import perform


def _source(root):
    root.mkdir()
    (root / "nested" / "empty").mkdir(parents=True)
    (root / ".hidden").write_bytes(b"hidden\r\n")
    (root / "nested" / "binary.bin").write_bytes(b"\x00\xff\xfe\r\n\x80")
    (root / "undeclared.txt").write_bytes(b"original\r\nbytes\r")
    return root


def test_establish_builds_the_workspace_from_the_archived_snapshot(tmp_path):
    tree = capture_public_tree(_source(tmp_path / "source"))
    environment = LocalEnvironment.establish(tmp_path / "workspace", tree)
    snapshot = environment.snapshot()
    facts = environment.query(FactsQuery(tree=True)).tree
    assert snapshot.tree == tree
    assert snapshot.digest == tree.digest
    assert facts is not None
    assert facts.digest == tree.digest
    assert facts.files == tuple(item.path for item in tree.files)
    assert ".checks" not in snapshot.tree.directories


def test_establish_without_a_snapshot_creates_an_empty_public_tree(tmp_path):
    environment = LocalEnvironment.establish(tmp_path / "workspace", None)
    snapshot = environment.snapshot()
    facts = environment.query(FactsQuery(tree=True)).tree
    assert snapshot.tree.files == ()
    assert snapshot.tree.directories == ()
    assert facts is not None
    assert facts.digest == snapshot.digest
    assert facts.files == ()


def test_establish_refuses_an_existing_destination(tmp_path):
    tree = capture_public_tree(_source(tmp_path / "source"))
    destination = tmp_path / "workspace"
    destination.mkdir()
    with pytest.raises(TreeError, match="already exists"):
        LocalEnvironment.establish(destination, tree)


def test_verify_tree_accepts_the_snapshot_it_was_read_from_and_rejects_a_change(tmp_path):
    environment = LocalEnvironment.establish(tmp_path / "workspace", capture_public_tree(_source(tmp_path / "source")))
    snapshot = environment.snapshot()
    environment.verify_tree(snapshot)
    result = perform(environment, "write_file", {"path": "later.txt", "content": "changed"}, department="quality")
    assert result.ok is True
    with pytest.raises(TreeError, match="complete recorded manifest"):
        environment.verify_tree(snapshot)
