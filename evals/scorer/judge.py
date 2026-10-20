"""场景 1 裁判（judge）：多模态裁判按 ArtifactsBench 1278 号题的 10 项清单打分。

裁判模型固定为 ag/gemini-3.8-flash-high（用户 2026-10-19 指定）。
裁判输入是界面智能体在每条用例关键状态截下的图，加上交付的全部代码。
总分 100 分，每项 0 至 10 分。
交付为空或启动失败时，不调用裁判，10 项直接记 0 分并写明原因。
"""

import base64
import json
import os
import re
import sys

JUDGE_MODEL = "ag/gemini-3.8-flash-high"

PROMPT_TEMPLATE = """You are a seasoned and meticulous code review expert, proficient in multiple programming languages, front-end technologies, and interaction design. Your task is to conduct an in-depth analysis and scoring of the received [question] and [answer]. The [answer] may include source code (in various programming languages), algorithm implementations, data structure designs, system architecture diagrams, front-end visualization code (such as HTML/SVG/JavaScript), interaction logic descriptions, and related technical explanations. Please leverage your coding expertise and aesthetic experience to thoroughly examine the [answer] content from the following dimensions and provide scores along with detailed review comments. You should be very strict and cautious when giving full marks for each dimension.

Role Definition

Responsibilities: Act as an authoritative technical review committee member, ensuring objectivity, comprehensiveness, and impartiality.
Attitude: Rigorous, professional, and unsparing, adept at identifying details and potential risks.
Additional Traits: Possess exceptional aesthetic talent, with high standards for visual appeal and user experience.

I have provided screenshots captured during test case execution and the delivery code.

**Scoring Criteria:**

{checklist_text}

- The final output should be a JSON object containing the dimensions above, following this example:
```json
{{
  "Overall Score": 62,
  "reason": "Detailed summary of the review...",
  "scores": [
    {{
      "id": 0,
      "title": "Is the basic CRUD functionality of the to-do list properly implemented?",
      "score": 10,
      "comment": "Reason for the score..."
    }}
  ]
}}
```

Please score the following question according to the standards above:

--------Problem starts--------
{question_text}
--------Problem ends--------

--------Answer starts--------
{answer_text}
--------Answer ends--------
"""

CODE_EXTENSIONS = {
    ".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".json",
    ".ts", ".jsx", ".tsx", ".vue", ".md", ".txt", ".py"
}

IGNORED_DIRS = {
    ".git", "node_modules", ".opencode-config", "__pycache__",
    "dist", "build", ".venv", "_work", "coverage"
}


def load_richness_checklist(richness_json_path):
    """加载 10 项丰富程度检查清单。"""
    with open(richness_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("checklist", [])


def make_zero_richness(checklist, reason="交付为空或服务启动失败，未执行评分"):
    """交付为空或无法启动时，10 项直接记 0 分并写明原因。"""
    items = []
    for item in checklist:
        items.append({
            "id": item["id"],
            "title": item["title"],
            "score": 0.0,
            "reason": reason,
        })
    return {
        "score": 0.0,
        "reason": reason,
        "items": items,
    }


def collect_delivery_code(delivery_dir, max_total_bytes=150000):
    """收集交付目录内的文本源码文件，忽略构建产物与二进制。"""
    if not os.path.isdir(delivery_dir):
        return "(No delivery directory found)"

    collected = []
    total_bytes = 0

    for root, dirs, files in os.walk(delivery_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        dirs.sort()
        for filename in sorted(files):
            _, ext = os.path.splitext(filename)
            if ext.lower() not in CODE_EXTENSIONS:
                continue
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, delivery_dir).replace("\\", "/")
            try:
                size = os.path.getsize(full_path)
                if total_bytes + size > max_total_bytes:
                    collected.append(f"\n=== File: {rel_path} (truncated due to total size limit) ===\n")
                    break
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                collected.append(f"\n=== File: {rel_path} ===\n{content}\n")
                total_bytes += len(content.encode("utf-8"))
            except Exception as exc:
                collected.append(f"\n=== File: {rel_path} (error reading: {exc}) ===\n")

    return "".join(collected) if collected else "(Empty delivery directory)"


def parse_judge_reply(reply_text, checklist):
    """解析裁判模型的 JSON 回复，发生格式异常时降级为 0 分并记录错误。"""
    if not reply_text or not reply_text.strip():
        return make_zero_richness(checklist, reason="裁判回复为空，无法解析评分")

    # 去掉思考模型可能存在的思考标签
    cleaned = reply_text.split("</think>")[-1].strip()

    # 优先匹配代码块里的 JSON
    json_str = None
    code_block_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned, re.IGNORECASE)
    if code_block_match:
        json_str = code_block_match.group(1)
    else:
        # 寻找首尾的花括号
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            json_str = cleaned[first_brace:last_brace + 1]

    if not json_str:
        return make_zero_richness(checklist, reason=f"裁判回复无法解析为 JSON：{cleaned[:200]}")

    try:
        data = json.loads(json_str)
    except Exception as exc:
        return make_zero_richness(checklist, reason=f"裁判回复 JSON 解析失败（{exc}）：{json_str[:200]}")

    if not isinstance(data, dict):
        return make_zero_richness(checklist, reason="裁判回复的 JSON 顶层不是对象")

    scores_list = data.get("scores") or data.get("items") or data.get("checklist")
    if not isinstance(scores_list, list) or not scores_list:
        return make_zero_richness(checklist, reason="裁判回复缺少有效打分列表（scores），无法解析")

    by_id = {}
    for entry in scores_list:
        if isinstance(entry, dict) and "id" in entry:
            try:
                by_id[int(entry["id"])] = entry
            except (ValueError, TypeError):
                pass

    parsed_items = []
    total_score = 0.0

    for idx, item in enumerate(checklist):
        entry = by_id.get(idx) or (scores_list[idx] if idx < len(scores_list) and isinstance(scores_list[idx], dict) else None)
        if entry:
            raw_score = entry.get("score")
            try:
                score_val = float(raw_score)
                score_val = max(0.0, min(10.0, score_val))
            except (ValueError, TypeError):
                score_val = 0.0
            comment = str(entry.get("comment") or entry.get("reason") or "No comment provided").strip()
        else:
            score_val = 0.0
            comment = "维度在裁判输出中缺失"

        parsed_items.append({
            "id": idx,
            "title": item["title"],
            "score": score_val,
            "reason": comment,
        })
        total_score += score_val
    # 若裁判提供了 Overall Score 且可转换，使用裁判给出的总体打分；否则使用各项总和
    if "Overall Score" in data:
        try:
            overall = float(data["Overall Score"])
            if 0.0 <= overall <= 100.0:
                total_score = overall
        except (ValueError, TypeError):
            pass

    return {
        "score": total_score,
        "reason": str(data.get("reason") or "").strip(),
        "items": parsed_items,
    }


def judge_richness(delivery_dir, screenshots, checklist, client=None, model=JUDGE_MODEL, requirement_text=None):
    """调用裁判模型对交付代码与截图进行打分。"""
    if not client:
        import openai
        api_base = os.environ.get("YUDAO_EVAL_BASE_URL")
        api_key = os.environ.get("YUDAO_EVAL_API_KEY")
        if not api_base or not api_key:
            return make_zero_richness(checklist, reason="缺少环境变量 YUDAO_EVAL_BASE_URL 或 YUDAO_EVAL_API_KEY，未调用裁判")
        client = openai.OpenAI(base_url=api_base, api_key=api_key)

    if requirement_text is None:
        scenario_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scenarios", "scenario-1"))
        req_file = os.path.join(scenario_root, "materials", "requirement.md")
        if os.path.isfile(req_file):
            with open(req_file, "r", encoding="utf-8") as f:
                requirement_text = f.read()
        else:
            requirement_text = "Advanced to-do list web application."

    checklist_lines = []
    for item in checklist:
        checklist_lines.append(
            f"Dimension {item['id']}: {item['title']}\n"
            f"Criteria: {item['description']}\n"
            f"Max Score: {item.get('maxScore', 10)}"
        )
    checklist_text = "\n\n".join(checklist_lines)

    code_text = collect_delivery_code(delivery_dir)

    prompt = PROMPT_TEMPLATE.format(
        checklist_text=checklist_text,
        question_text=requirement_text,
        answer_text=code_text,
    )

    user_content = [{"type": "text", "text": prompt}]

    for shot_path in screenshots:
        if os.path.isfile(shot_path):
            try:
                with open(shot_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"}
                })
            except Exception as exc:
                print(f"[Warning] Failed to read screenshot {shot_path}: {exc}", file=sys.stderr)

    messages = [{"role": "user", "content": user_content}]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0
        )
        reply = response.choices[0].message.content or ""
    except Exception as exc:
        return make_zero_richness(checklist, reason=f"调用裁判模型失败（{exc}）")

    return parse_judge_reply(reply, checklist)
