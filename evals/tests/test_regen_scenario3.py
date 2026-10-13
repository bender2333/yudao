"""重算脚本的可复现性：从仓库内固定的历史 JSON 重算，生成的
`docs/evaluation/scenario-3-yudao.json` 与 `.md` 与已提交的文件逐字节一致。

输入默认是 `evals/data/scenario-3-yudao-historical.json`（提交 `aaa91883` 的
旧版 JSON 原文，不可修改）；以已提交的新 JSON 为输入重算，结果同样逐字节一致
（幂等）。不调用 `gh`、不使用网络、不依赖 git 引用，浅克隆或无 origin 的检出里
也能通过。
"""
import json
import os
import re
import sys

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_DIR = os.path.join(EVALS_DIR, "runner")
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import regen_scenario3
ROOT = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
HISTORICAL_JSON = os.path.join(ROOT, "evals", "data", "scenario-3-yudao-historical.json")
COMMITTED_JSON = os.path.join(ROOT, "docs", "evaluation", "scenario-3-yudao.json")
COMMITTED_MD = os.path.join(ROOT, "docs", "evaluation", "scenario-3-yudao.md")


def _regenerate_to_tmp(tmp_path, source):
    json_out = str(tmp_path / "scenario-3-yudao.json")
    md_out = str(tmp_path / "scenario-3-yudao.md")
    args = ["--json-out", json_out, "--md-out", md_out]
    if source is not None:
        args = ["--source", source] + args
    assert regen_scenario3.main(args) == 0
    with open(json_out, encoding="utf-8") as handle:
        regenerated_json = handle.read()
    with open(md_out, encoding="utf-8") as handle:
        regenerated_md = handle.read()
    with open(COMMITTED_JSON, encoding="utf-8") as handle:
        committed_json = handle.read()
    with open(COMMITTED_MD, encoding="utf-8") as handle:
        committed_md = handle.read()
    return regenerated_json, regenerated_md, committed_json, committed_md


def test_regenerate_from_historical_input_matches_the_committed_files(tmp_path):
    assert regen_scenario3.DEFAULT_SOURCE == HISTORICAL_JSON
    regenerated_json, regenerated_md, committed_json, committed_md = (
        _regenerate_to_tmp(tmp_path, None))
    assert regenerated_json == committed_json
    assert regenerated_md == committed_md


def test_regenerate_from_committed_output_is_idempotent(tmp_path):
    regenerated_json, regenerated_md, committed_json, committed_md = (
        _regenerate_to_tmp(tmp_path, COMMITTED_JSON))
    assert regenerated_json == committed_json
    assert regenerated_md == committed_md


def test_regenerate_does_not_depend_on_git_or_network():
    with open(os.path.join(RUNNER_DIR, "regen_scenario3.py"), encoding="utf-8") as handle:
        text = handle.read()
    assert "subprocess" not in text
    assert "origin/main" not in text
    assert "git show" not in text


def test_regenerated_checkpoints_mark_unverifiable_fields(tmp_path):
    regenerated_json, _regenerated_md, _committed_json, _committed_md = (
        _regenerate_to_tmp(tmp_path, None))
    payload = json.loads(regenerated_json)
    notes = "\n".join(payload["notes"])
    assert "三次运行的版本比较（#324）尚未开展" in notes
    assert "来源未核实" in notes
    for run in payload["runs"]:
        checkpoints = run["metrics"]["checkpoints"]
        assert checkpoints["quality_release_bound_to_delivery"]["recheck_ratio_status"] in (
            "unverified", "frozen")
        assert "未核实" in checkpoints["replay_consistent"]["detail"]


def test_regenerated_details_state_the_missed_target(tmp_path):
    regenerated_json, regenerated_md, _committed_json, _committed_md = (
        _regenerate_to_tmp(tmp_path, None))
    text = regenerated_json + regenerated_md
    assert "阶段不是 DONE" in text
    assert "停止原因不是 released" in text
    repeats = [match.group(0)
               for match in re.finditer(r"(\S+)（实际为 (\S+?)）", text)
               if match.group(1) == match.group(2)]
    assert repeats == []
