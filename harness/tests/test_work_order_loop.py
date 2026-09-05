from harness.contracts import acceptance, clarification, defect, delivery, release
from harness.work_order_loop import run_three_department_loop


def test_happy_path_requires_quality_release():
    tickets = {
        "requirements": acceptance("build feature", ["feature works"]),
        "engineering": delivery("implemented feature", ["check passed"]),
        "quality": release(["check passed"]),
    }

    result = run_three_department_loop("build feature", lambda role, context: tickets[role])

    assert result.outcome == "done"
    assert result.stopped_reason == "released"
    assert result.transitions == [
        "requirements->engineering",
        "engineering->quality",
        "quality->done",
    ]
    assert [ticket.kind for ticket in result.tickets] == ["acceptance", "delivery", "release"]
    assert result.events[-1].detail == "released"


def test_clarification_returns_to_requirements_then_continues():
    sequence = iter([
        acceptance("build feature", ["feature works"]),
        clarification("what input format is required?"),
        acceptance("build feature", ["feature works for JSON input"]),
        delivery("implemented JSON input", ["check passed"]),
        release(["check passed"]),
    ])

    result = run_three_department_loop("build feature", lambda role, context: next(sequence))

    assert result.outcome == "done"
    assert result.transitions == [
        "requirements->engineering",
        "engineering->requirements",
        "requirements->engineering",
        "engineering->quality",
        "quality->done",
    ]


def test_quality_defect_routes_to_engineering():
    sequence = iter([
        acceptance("build feature", ["feature works"]),
        delivery("first implementation", ["check failed in QA"]),
        defect("engineering", "edge case fails"),
        delivery("fixed edge case", ["check passed"]),
        release(["check passed"]),
    ])

    result = run_three_department_loop("build feature", lambda role, context: next(sequence))

    assert result.outcome == "done"
    assert "quality->engineering" in result.transitions


def test_quality_defect_routes_to_requirements():
    sequence = iter([
        acceptance("build feature", ["feature works"]),
        delivery("implementation", ["check passed"]),
        defect("requirements", "acceptance misses an edge case"),
        acceptance("build feature", ["feature works for empty input"]),
        delivery("updated implementation", ["check passed"]),
        release(["check passed"]),
    ])

    result = run_three_department_loop("build feature", lambda role, context: next(sequence))

    assert result.outcome == "done"
    assert "quality->requirements" in result.transitions


def test_wrong_role_ticket_fails_closed():
    result = run_three_department_loop(
        "build feature",
        lambda role, context: delivery("wrong ticket", ["evidence"]),
    )

    assert result.outcome == "failed"
    assert result.stopped_reason == "contract_error"
    assert result.tickets == []


def test_max_cycles_is_explicit_failure():
    sequence = iter([
        acceptance("build feature", ["feature works"]),
        clarification("need a decision"),
    ])

    result = run_three_department_loop("build feature", lambda role, context: next(sequence), max_cycles=2)

    assert result.outcome == "failed"
    assert result.stopped_reason == "max_cycles"
