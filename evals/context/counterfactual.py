"""反事实回放：抽样若干步，同一模型（温度 0）分别回答旧视图与新视图，比动作是否一致。

做法（设计说明第 6.2 节）：

1. 抽样：按部门分层、按步序分桶，用固定种子随机取 N 步（默认 24）。
2. 每一步问两次：一次用记录下来的请求（旧视图），一次用 `view()` 装配的请求（新视图）。
   两次除消息之外的一切相同：同一模型、同一工具定义、温度 0、不带推理档位。
3. 比「动作」：第一次工具调用的名字与参数，按参数规范化以后比较；没有工具调用时比
   「只回复文字」。一致率按步计。
4. 不一致的逐个写出：模型在新视图上做了什么、旧视图上做了什么，附各自的原因说明
   （这一步视图里少了什么、多了什么），由人读一遍，判断是「新视图确实丢了东西」还是
   「同一件事换了个说法」。

凭据只从环境变量读：YUDAO_EVAL_BASE_URL、YUDAO_EVAL_API_KEY、YUDAO_EVAL_MODEL。
不写进任何文件、日志与提交。
"""

from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .items import normalize_request, tokens_of
from .measure import measure_run
from .store import EventLog
from .view import Rules, load_rules, view

ENV_BASE = "YUDAO_EVAL_BASE_URL"
ENV_KEY = "YUDAO_EVAL_API_KEY"
ENV_MODEL = "YUDAO_EVAL_MODEL"


@dataclass
class Sample:
    run_id: str
    step_id: int
    department: str
    old_tokens: int
    new_tokens: int
    old_action: dict[str, Any] | None
    new_action: dict[str, Any] | None
    old_repeat_action: dict[str, Any] | None
    old_text: str
    new_text: str
    old_usage: dict[str, Any] | None
    new_usage: dict[str, Any] | None


def _sample_steps(log: EventLog, rules: Rules, size: int, seed: int) -> list[tuple[str, int]]:
    """按部门分层、按步序分桶抽样：小样本也要覆盖三个部门与前中后段。"""
    buckets: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for run_id in log.runs():
        for step in log.steps(run_id):
            index = "1" if step.step_id == 1 else "2-3" if step.step_id <= 3 else "4-7" if step.step_id <= 7 else "8+"
            buckets.setdefault((step.department or "?", index), []).append((run_id, step.step_id))
    rng = random.Random(seed)
    for items in buckets.values():
        items.sort()
    keys = sorted(buckets)
    picked: list[tuple[str, int]] = []
    while len(picked) < size and keys:
        for key in list(keys):
            items = buckets[key]
            if not items:
                keys.remove(key)
                continue
            picked.append(items.pop(rng.randrange(len(items))))
            if len(picked) >= size:
                break
    return picked


def _request(body: dict[str, Any], model: str) -> dict[str, Any]:
    """发给模型的请求：消息与工具原样，加模型名、温度 0、不要流式。"""
    payload: dict[str, Any] = {
        "model": model,
        "messages": body["messages"],
        "temperature": 0,
        "stream": False,
    }
    if body.get("tools"):
        payload["tools"] = body["tools"]
    return payload


def _post(base_url: str, key: str, payload: dict[str, Any], timeout: int = 600) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"模型服务返回 {error.code}：{detail}") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _from_stream(text)


def _from_stream(text: str) -> dict[str, Any]:
    """模型服务忽略 stream=false 时按 SSE 片段拼回一次回答（内容与工具调用都拼）。"""
    content: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            event = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if event.get("usage"):
            usage = event["usage"]
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content.append(delta["content"])
            for call in delta.get("tool_calls") or []:
                index = int(call.get("index") or 0)
                slot = calls.setdefault(index, {"id": "", "type": "function",
                                                "function": {"name": "", "arguments": ""}})
                if call.get("id"):
                    slot["id"] = call["id"]
                function = call.get("function") or {}
                if function.get("name"):
                    slot["function"]["name"] += function["name"]
                if function.get("arguments"):
                    slot["function"]["arguments"] += function["arguments"]
    message: dict[str, Any] = {"content": "".join(content) or None}
    if calls:
        message["tool_calls"] = [calls[index] for index in sorted(calls)]
    return {"choices": [{"message": message}], "usage": usage}


def _action(reply: dict[str, Any]) -> dict[str, Any]:
    """把一次回答归一成「动作」：这一轮要做的工具调用（名字与参数），或者只回复文字。"""
    choice = (reply.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    calls = message.get("tool_calls") or []
    if not calls:
        return {"kind": "text"}
    steps = []
    for call in calls:
        function = call.get("function") or {}
        arguments = function.get("arguments")
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            parsed = arguments
        steps.append({"tool": function.get("name"), "arguments": _normalise(parsed)})
    steps.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return {"kind": "call", "calls": steps}


def _normalise(value: Any) -> Any:
    """参数的规范化：键排序、字符串去首尾空白。只有路径与命令的空白差异不算动作不同。"""
    if isinstance(value, dict):
        return {key: _normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    return value


def _same(old: dict[str, Any] | None, new: dict[str, Any] | None) -> bool:
    if old is None or new is None:
        return False
    return old == new


def main(db_path: str, artifacts_root: str | None, rules_path: str, size: int,
         temperature: float, out_path: str, seed: int) -> int:
    base_url = os.environ.get(ENV_BASE)
    key = os.environ.get(ENV_KEY)
    model = os.environ.get(ENV_MODEL)
    missing = [name for name, value in ((ENV_BASE, base_url), (ENV_KEY, key), (ENV_MODEL, model)) if not value]
    if missing:
        print(f"缺少环境变量：{', '.join(missing)}；反事实回放需要真实模型。")
        return 2
    rules = load_rules(rules_path)
    samples: list[Sample] = []
    with EventLog(db_path, artifacts_root) as log:
        picked = _sample_steps(log, rules, size, seed)
        cache: dict[str, list] = {}
        for run_id, step_id in picked:
            views = cache.get(run_id)
            if views is None:
                views = measure_run(log, run_id)
                cache[run_id] = views
            item = next((view_ for view_ in views if view_.step_id == step_id), None)
            step = next((step_ for step_ in log.steps(run_id) if step_.step_id == step_id), None)
            if item is None or step is None:
                continue
            old_body = {"messages": step.body.get("messages"), "tools": step.body.get("tools")}
            new_body = view(item.entries, rules, tools=step.body.get("tools"))
            old_reply = _post(base_url, key, _request(old_body, model))
            new_reply = _post(base_url, key, _request(new_body, model))
            # 同一请求再问一次：温度 0 不保证模型逐字相同，这是「同一视图」的一致率基线
            repeat_reply = _post(base_url, key, _request(old_body, model))
            samples.append(Sample(
                run_id=run_id, step_id=step_id, department=item.department,
                old_tokens=tokens_of(item.entries),
                new_tokens=tokens_of(normalize_request(new_body, step_id)),
                old_action=_action(old_reply), new_action=_action(new_reply),
                old_repeat_action=_action(repeat_reply),
                old_text=_excerpt(old_reply), new_text=_excerpt(new_reply),
                old_usage=(old_reply.get("usage") or {}), new_usage=(new_reply.get("usage") or {}),
            ))
            print(f"{run_id} 第 {step_id} 步（{item.department}）：旧对新 "
                  f"{'一致' if _same(samples[-1].old_action, samples[-1].new_action) else '不一致'}；"
                  f"旧对旧 {'一致' if _same(samples[-1].old_action, samples[-1].old_repeat_action) else '不一致'}")
    agree = [sample for sample in samples if _same(sample.old_action, sample.new_action)]
    baseline = [sample for sample in samples if _same(sample.old_action, sample.old_repeat_action)]
    result = {
        "rules_version": rules.version(),
        "model": model,
        "temperature": temperature,
        "sampled": len(samples),
        "agreement": len(agree),
        "agreement_rate": round(len(agree) / max(1, len(samples)), 4),
        "self_agreement": len(baseline),
        "self_agreement_rate": round(len(baseline) / max(1, len(samples)), 4),
        "by_department": {},
        "samples": [
            {"run_id": sample.run_id, "step_id": sample.step_id, "department": sample.department,
             "old_tokens": sample.old_tokens, "new_tokens": sample.new_tokens,
             "agree": _same(sample.old_action, sample.new_action),
             "self_agree": _same(sample.old_action, sample.old_repeat_action),
             "old_action": sample.old_action, "new_action": sample.new_action,
             "repeat_action": sample.old_repeat_action,
             "old_text": sample.old_text, "new_text": sample.new_text,
             "old_usage": sample.old_usage, "new_usage": sample.new_usage}
            for sample in samples
        ],
    }
    for sample in samples:
        row = result["by_department"].setdefault(sample.department, {"sampled": 0, "agree": 0, "self_agree": 0})
        row["sampled"] += 1
        row["agree"] += 1 if _same(sample.old_action, sample.new_action) else 0
        row["self_agree"] += 1 if _same(sample.old_action, sample.old_repeat_action) else 0
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"旧对新一致 {len(agree)}/{len(samples)} = {result['agreement_rate']}；"
          f"旧对旧一致 {len(baseline)}/{len(samples)} = {result['self_agreement_rate']}")
    return 0


def _excerpt(reply: dict[str, Any]) -> str:
    choice = (reply.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = (message.get("content") or "").strip()
    return text[:300]


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1], None, "evals/context/rule-set.json", 24, 0.0,
                  "docs/evaluation/context-assembly-counterfactual-2026-10-29.json", 912))
