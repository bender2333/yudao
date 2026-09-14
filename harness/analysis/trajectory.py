"""Recompute issue trajectories from verified observations. Never trust stored analysis."""

from __future__ import annotations

from .records import (
    ANALYZER,
    Issue,
    LoadedRound,
    QAContrast,
    Trajectory,
    TrajectoryPoint,
)


def recompute_trajectory(rounds: tuple[LoadedRound, ...]) -> Trajectory:
    issues = []
    seen = []
    for item in rounds:
        for requirement in item.requirements:
            key = (requirement.id, requirement.version)
            if key not in seen:
                seen.append(key)
    for requirement_id, version in seen:
        points = []
        comparable = True
        environment = None
        check_id = None
        for item in rounds:
            match = next((req for req in item.requirements if req.id == requirement_id), None)
            if match is None:
                continue
            if match.version != version:
                comparable = False
                break
            related = [check for check in item.checks if check.requirement_id == requirement_id]
            if len(related) != 1:
                comparable = False
                break
            check = related[0]
            observation = next((obs for obs in item.observations if obs.check_id == check.id), None)
            if observation is None:
                comparable = False
                break
            if check_id is None:
                check_id = check.id
                environment = _environment_key(item)
            elif check.id != check_id or _environment_key(item) != environment:
                comparable = False
                break
            points.append(
                TrajectoryPoint(
                    round_id=item.id,
                    check_id=check.id,
                    verdict=observation.verdict,
                    stdin_path=observation.stdin_path,
                    stdout_path=observation.stdout_path,
                    stderr_path=observation.stderr_path,
                    exit_code=observation.exit_code,
                    termination=observation.termination,
                )
            )
        status = _status(tuple(point.verdict for point in points)) if comparable and points else "not_comparable"
        issues.append(Issue(requirement_id=requirement_id, status=status, points=tuple(points)))
    return Trajectory(analyzer=ANALYZER, issues=tuple(issues), qa_contrasts=_qa_contrasts(rounds))


def _environment_key(item: LoadedRound) -> tuple[str, str, str]:
    env = item.environment
    return (env.interpreter, env.executor, env.comparison_rules)


def _status(verdicts: tuple[str, ...]) -> str:
    if any(value == "unknown" for value in verdicts):
        return "not_comparable"
    if not verdicts:
        return "not_comparable"
    fails = [index for index, value in enumerate(verdicts) if value == "fail"]
    passes = [index for index, value in enumerate(verdicts) if value == "pass"]
    if not fails:
        return "stable"
    if not passes:
        return "persistent"
    first_fail, last_fail = fails[0], fails[-1]
    first_pass, last_pass = passes[0], passes[-1]
    if first_fail < first_pass < last_fail:
        return "regressed"
    if first_pass < first_fail:
        return "new_failure"
    return "repaired"


def _qa_contrasts(rounds: tuple[LoadedRound, ...]) -> tuple[QAContrast, ...]:
    contrasts = []
    for item in rounds:
        if item.qa is None:
            continue
        failed = tuple(
            check.requirement_id
            for check in item.checks
            for observation in item.observations
            if observation.check_id == check.id and observation.verdict == "fail"
        )
        reviewed_failed = tuple(
            requirement_id
            for requirement_id in failed
            if requirement_id in item.qa.reviewed_requirement_ids
        )
        if item.qa.decision != "release":
            reason = "not_a_release"
            confirmed = False
        elif not reviewed_failed:
            reason = "no_reviewed_counterexample"
            confirmed = False
        elif item.qa.delivery_digest is None:
            reason = "missing_delivery_evidence"
            confirmed = False
        elif item.qa.delivery_digest != item.delivery.digest:
            reason = "delivery_digest_mismatch"
            confirmed = False
        else:
            reason = "reviewed_requirement_failed"
            confirmed = True
        contrasts.append(
            QAContrast(
                round_id=item.id,
                decision=item.qa.decision,
                confirmed_false_release=confirmed,
                counterexamples=reviewed_failed,
                reason=reason,
            )
        )
    return tuple(contrasts)
