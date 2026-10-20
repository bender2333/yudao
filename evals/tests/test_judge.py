"""场景 1 裁判（judge）与丰富程度清单测试。

不需要模型的用例（清单结构与出处、分数汇总、裁判回复解析失败处理、空目录交付）在 CI check 中运行；
调用真实裁判模型的用例带 real_model 标记。
"""

import importlib.util
import json
import os
import sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIO1_DIR = os.path.abspath(os.path.join(HERE, "..", "scenarios", "scenario-1"))
CHECKS_DIR = os.path.join(SCENARIO1_DIR, "checks")
SCORER_DIR = os.path.abspath(os.path.join(HERE, "..", "scorer"))


def _load_judge():
    judge_path = os.path.join(SCORER_DIR, "judge.py")
    spec = importlib.util.spec_from_file_location("evals_scorer_judge", judge_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


judge = _load_judge()
parse_judge_reply = judge.parse_judge_reply
load_richness_checklist = judge.load_richness_checklist
collect_delivery_code = judge.collect_delivery_code
judge_richness = judge.judge_richness

real_model = pytest.mark.real_model


def test_richness_checklist_source_and_structure():
    """核对丰富程度 10 项清单的来源、提交号与数据结构。"""
    richness_path = os.path.join(CHECKS_DIR, "richness.json")
    assert os.path.isfile(richness_path), "richness.json 必须存在"

    with open(richness_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    source = data["source"]
    assert "ArtifactsBenchmark" in source["repository"]
    assert source["commit"] == "88c968b"
    assert source["task_index"] == 1278

    checklist = data["checklist"]
    assert len(checklist) == 10

    # 10 项清单：id 0..9，maxScore 10
    for idx, item in enumerate(checklist):
        assert item["id"] == idx
        assert "title" in item and len(item["title"]) > 0
        assert "description" in item and len(item["description"]) > 0
        assert item["maxScore"] == 10

    # 前 4 项为待办清单功能专属条目（CRUD、优先级与分类、持久化存储、截止与提醒）
    assert "CRUD" in checklist[0]["title"] or "CRUD" in checklist[0]["description"]
    assert "prioritization" in checklist[1]["title"].lower() or "categorization" in checklist[1]["title"].lower()
    assert "storage" in checklist[2]["title"].lower() or "persistence" in checklist[2]["description"].lower()
    assert "scheduling" in checklist[3]["title"].lower() or "notification" in checklist[3]["title"].lower()

    # 后 6 项为通用条目（健壮性、创新功能、冗余功能、工程质量、界面视觉、动态交互）
    assert "robust" in checklist[4]["title"].lower()
    assert "innovative" in checklist[5]["title"].lower()
    assert "redundant" in checklist[6]["title"].lower()
    assert "engineering" in checklist[7]["title"].lower()
    assert "vision" in checklist[8]["title"].lower() or "visual" in checklist[8]["description"].lower()
    assert "interaction" in checklist[9]["title"].lower() or "dynamic" in checklist[9]["title"].lower()


def test_parse_judge_reply_valid_json():
    """裁判返回合法 JSON 时能正确解析总分与 10 项细则。"""
    checklist = load_richness_checklist(os.path.join(CHECKS_DIR, "richness.json"))
    sample_scores = [
        {"id": i, "title": checklist[i]["title"], "score": 8, "comment": f"Good item {i}"}
        for i in range(10)
    ]
    raw_payload = {
        "Overall Score": 80,
        "reason": "Overall good implementation.",
        "scores": sample_scores
    }
    reply_text = json.dumps(raw_payload)

    parsed = parse_judge_reply(reply_text, checklist)
    assert parsed["score"] == 80
    assert len(parsed["items"]) == 10
    for idx, it in enumerate(parsed["items"]):
        assert it["id"] == idx
        assert it["score"] == 8
        assert it["reason"] == f"Good item {idx}"


def test_parse_judge_reply_in_markdown_code_block():
    """裁判返回包含 markdown 代码块的文本时能正确提取并解析。"""
    checklist = load_richness_checklist(os.path.join(CHECKS_DIR, "richness.json"))
    raw_json = json.dumps({
        "Overall Score": 65,
        "reason": "Decent implementation.",
        "scores": [
            {"id": i, "title": checklist[i]["title"], "score": 6 if i < 5 else 7, "comment": f"Comment {i}"}
            for i in range(10)
        ]
    })
    reply_text = f"Here is my evaluation:\n```json\n{raw_json}\n```\nHope this helps."

    parsed = parse_judge_reply(reply_text, checklist)
    assert parsed["score"] == 65
    assert len(parsed["items"]) == 10
    assert parsed["items"][0]["score"] == 6
    assert parsed["items"][9]["score"] == 7


def test_parse_judge_reply_malformed_fallback():
    """裁判返回乱码或无法解析的内容时，降级处理为 0 分并写明原因，不抛出异常。"""
    checklist = load_richness_checklist(os.path.join(CHECKS_DIR, "richness.json"))
    corrupted_replies = [
        "",
        "I am unable to score this.",
        "```json\n{ broken json here \n```",
        "{\"Overall Score\": \"not a number\", \"scores\": null}"
    ]

    for corrupted in corrupted_replies:
        parsed = parse_judge_reply(corrupted, checklist)
        assert parsed["score"] == 0
        assert len(parsed["items"]) == 10
        for it in parsed["items"]:
            assert it["score"] == 0
            assert "解析失败" in it["reason"] or "无法解析" in it["reason"] or "error" in it["reason"].lower()


def test_collect_delivery_code(tmp_path):
    """提取交付代码时忽略 .git、node_modules 与二进制，收集文本源码。"""
    delivery = tmp_path / "test_delivery"
    delivery.mkdir()
    (delivery / "index.html").write_text("<!DOCTYPE html><html><body>Test</body></html>", encoding="utf-8")
    (delivery / "app.js").write_text("console.log('hello');", encoding="utf-8")

    nm = delivery / "node_modules" / "somepkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("module.exports = {};", encoding="utf-8")

    git_dir = delivery / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]", encoding="utf-8")

    binary = delivery / "test.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00")

    code_text = collect_delivery_code(str(delivery))
    assert "index.html" in code_text
    assert "app.js" in code_text
    assert "somepkg" not in code_text
    assert ".git" not in code_text
    assert "\x89PNG" not in code_text


@real_model
def test_real_model_judge_reference():
    """调用真实裁判模型对参考实现与截图打分。"""
    checklist = load_richness_checklist(os.path.join(CHECKS_DIR, "richness.json"))
    ref_dir = os.path.join(SCENARIO1_DIR, "reference")
    result = judge_richness(ref_dir, [], checklist)
    assert 0 <= result["score"] <= 100
    assert len(result["items"]) == 10
    for it in result["items"]:
        assert 0 <= it["score"] <= 10
        assert isinstance(it["reason"], str) and len(it["reason"]) > 0
