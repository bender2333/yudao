"""A4 comparison runner: FakeAdapter only, no network, no real Provider."""

import pytest

from harness.adapters.fake import FakeAdapter
from harness.compare import (
    CANDIDATE_PARAGRAPHS,
    candidate_engineering_prompt,
    comparison_script,
    run_a4_comparison,
)
from harness.department_prompts import DEFAULT_PROMPTS
from harness.tests.helpers import system_with


@pytest.fixture(scope="module")
def comparison(tmp_path_factory):
    system = system_with(tmp_path_factory.mktemp("loop"), comparison_script())
    out = tmp_path_factory.mktemp("a4-out")
    report = run_a4_comparison(system, out)
    return system, report, out


def test_baseline_writes_before_plan_candidate_plans_first(comparison):
    _system, report, _out = comparison
    assert [task["order"] for task in report["tasks"]] == [
        ["baseline", "candidate"],
        ["candidate", "baseline"],
        ["baseline", "candidate"],
        ["candidate", "baseline"],
    ]
    baseline = [trial for trial in report["trials"] if trial["group"] == "baseline"]
    candidate = [trial for trial in report["trials"] if trial["group"] == "candidate"]
    assert len(baseline) == len(candidate) == 4
    assert all(trial["writes_before_plan_accepted"] for trial in baseline)
    assert not any(trial["writes_before_plan_accepted"] for trial in candidate)
    assert all(trial["plan_accepted_count"] >= 1 for trial in report["trials"])


def test_candidate_engineering_initial_prompt_contains_protocol_paragraphs(comparison):
    system, report, _out = comparison
    addendum = candidate_engineering_prompt()
    assert addendum.startswith(DEFAULT_PROMPTS["engineering"])
    assert all(paragraph in addendum for paragraph in CANDIDATE_PARAGRAPHS)
    assert all(paragraph not in DEFAULT_PROMPTS["engineering"] for paragraph in CANDIDATE_PARAGRAPHS)

    candidate_runs = {trial["run_id"] for trial in report["trials"] if trial["group"] == "candidate"}
    baseline_runs = {trial["run_id"] for trial in report["trials"] if trial["group"] == "baseline"}
    for trial in report["trials"]:
        projection = system.project(trial["run_id"])
        engineering = projection.department_prompts["engineering"].text
        product = projection.department_prompts["product"].text
        quality = projection.department_prompts["quality"].text
        if trial["group"] == "candidate":
            assert all(paragraph in engineering for paragraph in CANDIDATE_PARAGRAPHS)
            assert trial["engineering_prompt_has_candidate_addendum"] is True
            assert trial["prompt_config_versions"]["engineering"] == 1
        else:
            assert all(paragraph not in engineering for paragraph in CANDIDATE_PARAGRAPHS)
            assert engineering == DEFAULT_PROMPTS["engineering"]
            assert trial["engineering_prompt_has_candidate_addendum"] is False
            assert trial["prompt_config_versions"]["engineering"] == 0
        assert all(paragraph not in product for paragraph in CANDIDATE_PARAGRAPHS)
        assert all(paragraph not in quality for paragraph in CANDIDATE_PARAGRAPHS)
        assert product == DEFAULT_PROMPTS["product"]
        assert quality == DEFAULT_PROMPTS["quality"]

    adapter = system.test_adapter
    assert isinstance(adapter, FakeAdapter)
    for request in adapter.invocations:
        if request.purpose != "work" or not request.input_items:
            continue
        content = request.input_items[0]["content"]
        has_addendum = all(paragraph in content for paragraph in CANDIDATE_PARAGRAPHS)
        candidate_engineering = request.department == "engineering" and request.run_id in candidate_runs
        assert has_addendum is candidate_engineering
        if request.run_id in baseline_runs:
            assert not has_addendum


def test_baseline_requests_unaffected_after_candidate_v1(comparison):
    system, report, _out = comparison
    projects = report["projects"]
    assert projects["baseline"]["prompt_configs"]["engineering"]["version"] == 0
    assert projects["candidate"]["prompt_configs"]["engineering"]["version"] == 1
    assert projects["candidate"]["prompt_configs"]["engineering"]["has_candidate_addendum"] is True
    assert projects["baseline"]["prompt_configs"]["engineering"]["has_candidate_addendum"] is False
    assert projects["candidate"]["prompt_configs"]["product"]["version"] == 0
    assert projects["candidate"]["prompt_configs"]["quality"]["version"] == 0

    baseline_id = projects["baseline"]["project_id"]
    current = system.projects.read_prompt(baseline_id, "engineering")
    assert current["version"] == 0 and current["text"] == DEFAULT_PROMPTS["engineering"]
    for trial in report["trials"]:
        if trial["group"] != "baseline":
            continue
        assert trial["prompt_config_versions"] == {"product": 0, "engineering": 0, "quality": 0}
        for request in system.test_adapter.invocations:
            if request.run_id != trial["run_id"] or request.purpose != "work":
                continue
            assert all(paragraph not in request.input_items[0]["content"] for paragraph in CANDIDATE_PARAGRAPHS)


def test_comparison_writes_report_without_network(comparison):
    system, report, out = comparison
    assert system.test_adapter.name == "fake"
    assert system.provider_catalog is None
    assert report["conclusion"] == "undecided"
    markdown = (out / "a4-compare.md").read_text(encoding="utf-8")
    assert "结论：`undecided`" in markdown
    assert len(report["trials"]) == 8
    json_text = (out / "a4-compare.json").read_text(encoding="utf-8")
    assert '"conclusion": "undecided"' in json_text
    assert (out / "a4-compare.md").is_file()
    assert all(trial.get("summary") for trial in report["trials"])
