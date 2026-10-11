"""重算脚本的可复现性：从旧版 JSON（`origin/main` 上的文档）重算，生成的
`docs/evaluation/scenario-3-yudao.json` 与 `.md` 与已提交的文件逐字节一致。

不调用 `gh`、不使用网络；子进程只读仓库内 git 对象（`git show origin/main:...`）。
输入不可识别为 git 引用时改读本地路径，仍是仓库内的文件。
"""
import json
import os
import sys

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_DIR = os.path.join(EVALS_DIR, "runner")
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import regen_scenario3
ROOT = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
COMMITTED_JSON = os.path.join(ROOT, "docs", "evaluation", "scenario-3-yudao.json")
COMMITTED_MD = os.path.join(ROOT, "docs", "evaluation", "scenario-3-yudao.md")


def test_regenerate_matches_the_committed_files(tmp_path):
    json_out = str(tmp_path / "scenario-3-yudao.json")
    md_out = str(tmp_path / "scenario-3-yudao.md")
    assert regen_scenario3.main(["--json-out", json_out, "--md-out", md_out]) == 0
    with open(json_out, encoding="utf-8") as handle:
        regenerated_json = handle.read()
    with open(md_out, encoding="utf-8") as handle:
        regenerated_md = handle.read()
    with open(COMMITTED_JSON, encoding="utf-8") as handle:
        committed_json = handle.read()
    with open(COMMITTED_MD, encoding="utf-8") as handle:
        committed_md = handle.read()
    assert regenerated_json == committed_json
    assert regenerated_md == committed_md


def test_regenerated_checkpoints_mark_unverifiable_fields(tmp_path):
    json_out = str(tmp_path / "scenario-3-yudao.json")
    md_out = str(tmp_path / "scenario-3-yudao.md")
    assert regen_scenario3.main(["--json-out", json_out, "--md-out", md_out]) == 0
    with open(json_out, encoding="utf-8") as handle:
        payload = json.load(handle)
    notes = "\n".join(payload["notes"])
    assert "三次运行的版本比较（#324）尚未开展" in notes
    assert "来源未核实" in notes
    for run in payload["runs"]:
        checkpoints = run["metrics"]["checkpoints"]
        assert checkpoints["quality_release_bound_to_delivery"]["recheck_ratio_status"] in (
            "unverified", "frozen")
        assert "未核实" in (checkpoints["no_write_before_plan_accepted"]["detail"]
                            + checkpoints["replay_consistent"]["detail"])
