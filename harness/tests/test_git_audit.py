import hashlib
import os
import subprocess

import pytest

from harness.adapters.fake import FakeAdapter
from harness.git_audit import GitBindingError, git_version_detail, verify_git_history
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.saved_rewrite import rewrite_saved_events

def test_detail_rejects_valid_current_tree_with_unaccepted_parent_materials(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), delivery_turn(), review_turn("release", "Independent checks passed"),
    ]))
    run_id = system.create_run("build echo")
    try:
        assert system.run_until_stop(run_id).phase == "DONE"
        assert verify_git_history(system.git_versions, system.artifacts, system.store.list_events(run_id))
        events = system.store.list_events(run_id)
        delivery = next(event for event in events if event.type == EventType.DELIVERY_ACCEPTED)
        quality = next(event for event in events if event.type == EventType.QA_SUBMITTED)
        delivered, accepted = delivery.payload["git_version"], quality.payload["git_version"]
        repo = tmp_path / "git" / (run_id + ".git")
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        environment.update({
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Independent audit", "GIT_AUTHOR_EMAIL": "audit@example.invalid",
            "GIT_COMMITTER_NAME": "Independent audit", "GIT_COMMITTER_EMAIL": "audit@example.invalid",
        })

        def git(*arguments, data=None):
            return subprocess.run(
                ["git", "--git-dir=" + str(repo), "-c", "core.hooksPath=" + str(tmp_path / "no-hooks"), *arguments],
                input=data, capture_output=True, check=True, shell=False, env=environment,
            ).stdout

        def commit(tree, parent, original):
            message = git("cat-file", "commit", original).split(b"\n\n", 1)[1]
            oid = git("commit-tree", tree, "-p", parent, data=message).decode("ascii").strip()
            git("update-ref", "refs/snapshots/" + oid, oid)
            raw = git("cat-file", "commit", oid)
            assert hashlib.sha1(b"commit " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest() == oid
            header = raw.split(b"\n\n", 1)[0].splitlines()
            assert ("tree " + tree).encode("ascii") in header
            assert ("parent " + parent).encode("ascii") in header
            return {"commit": oid, "parent_commit": parent, "tree": tree}

        # Both objects are valid Git commits; only the parent's accepted PRD binding is false.
        unaccepted = b"UNACCEPTED_PARENT_REQUIREMENTS\n"
        blob = git("hash-object", "-w", "--stdin", "--no-filters", data=unaccepted).strip()
        entries = [entry for entry in git("ls-tree", "-z", delivered["tree"]).split(b"\0") if entry]
        entries = [b"100644 blob " + blob + b"\tPRD.md" if entry.endswith(b"\tPRD.md") else entry for entry in entries]
        tree = git("mktree", "-z", data=b"\0".join(entries) + b"\0").decode("ascii").strip()
        wrong_parent = commit(tree, delivered["parent_commit"], delivered["commit"])
        current = commit(accepted["tree"], wrong_parent["commit"], accepted["commit"])
        assert git("cat-file", "blob", wrong_parent["commit"] + ":PRD.md") == unaccepted
        assert current["tree"] == accepted["tree"]
        raw_diff = git("diff-tree", "-p", "--no-ext-diff", "--no-textconv", current["commit"])
        assert unaccepted.rstrip(b"\n") in raw_diff

        delivery.payload["git_version"] = wrong_parent
        quality.payload["git_version"] = current
        rewrite_saved_events(system.store, [delivery, quality])
        recorded = system.store.list_events(run_id)
        with pytest.raises(GitBindingError, match="accepted event materials"):
            verify_git_history(system.git_versions, system.artifacts, recorded)
        recorded_quality = next(item for item in recorded if item.event_id == quality.event_id)
        with pytest.raises(GitBindingError, match="accepted event materials"):
            git_version_detail(system.git_versions, system.artifacts, recorded, recorded_quality)
    finally:
        system.store.close()
