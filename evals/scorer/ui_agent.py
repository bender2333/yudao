"""场景 1 界面智能体：在浏览器中按可见内容执行用例并截图。

界面智能体沿用 WebGen-Bench 评测脚本的做法，使用 Playwright 操作 Chromium，
每条用例最多 15 步交互，给出通过（1）、部分通过（0.5）、不通过（0）；
找不到对应的元素或入口时记为「没有做」（not_done，记 0）。
在每条用例的关键状态截图，留给裁判打分。

模型使用 ag/gemini-3.8-flash-high，经 YUDAO_EVAL_BASE_URL 与 YUDAO_EVAL_API_KEY
调用，凭据不写入结果、日志与工单。
"""

import base64
import os
import re
import time

DEFAULT_MODEL = "ag/gemini-3.8-flash-high"
MAX_STEPS = 15

SYSTEM_PROMPT = """You are a web UI testing agent. Your job is to test a web application according to a specific task and verify the expected result.

In each turn, you receive:
1. Current page screenshot.
2. List of interactive web elements with numerical IDs.

You can perform one action per turn:
- Click [ID]  (e.g., Click 1)
- Type [ID]; [Text]  (e.g., Type 2; Buy groceries)
- Scroll [up/down]
- Wait
- ANSWER: [YES | PARTIAL | NO | NOT_DONE]; [Reason]

ANSWER guidelines:
- YES: The task was attempted and the expected result is fully achieved.
- PARTIAL: Some aspects of expected result were achieved, but not all.
- NO: The task was attempted (controls were present and used), but the expected result failed.
- NOT_DONE: The relevant form, button, input, menu, or entry point for this task does NOT exist on the page.

You have at most 15 turns. When you have enough evidence or conclude the result, output ANSWER."""


def get_interactive_elements(page):
    """提取页面上的可交互元素及其简要描述与序号。"""
    js = """
    () => {
      const elements = [];
      const nodes = document.querySelectorAll('button, input, a, select, textarea, [role="button"], [onclick]');
      let idx = 1;
      for (const el of nodes) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none') {
          const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim();
          elements.push({
            id: idx++,
            tag: el.tagName.toLowerCase(),
            type: el.type || '',
            text: text.slice(0, 60),
            selector: el.id ? '#' + el.id : (el.name ? '[name="' + el.name + '"]' : null)
          });
        }
      }
      return elements;
    }
    """
    try:
        return page.evaluate(js)
    except Exception:
        return []


def format_elements(elements):
    lines = []
    for el in elements:
        desc = f"[{el['id']}] <{el['tag']}"
        if el['type']:
            desc += f" type='{el['type']}'"
        desc += ">"
        if el['text']:
            desc += f" \"{el['text']}\""
        lines.append(desc)
    return "\n".join(lines) if lines else "(No interactive elements found)"


def parse_action(content):
    """解析模型返回的操作与回答。"""
    answer_match = re.search(r"ANSWER:\s*(YES|PARTIAL|NO|NOT_DONE)", content, re.IGNORECASE)
    if answer_match:
        verdict = answer_match.group(1).upper()
        reason = content[answer_match.end():].strip().lstrip(";").strip()
        return "answer", verdict, reason

    click_match = re.search(r"Click\s*\[?(\d+)\]?", content, re.IGNORECASE)
    if click_match:
        return "click", int(click_match.group(1)), None

    type_match = re.search(r"Type\s*\[?(\d+)\]?;\s*(.+)", content, re.IGNORECASE)
    if type_match:
        return "type", int(type_match.group(1)), type_match.group(2).strip()

    scroll_match = re.search(r"Scroll\s*(up|down)", content, re.IGNORECASE)
    if scroll_match:
        return "scroll", scroll_match.group(1).lower(), None

    if re.search(r"Wait", content, re.IGNORECASE):
        return "wait", None, None

    return "unknown", content, None


def execute_action(page, action_type, arg1, arg2, elements):
    """在 Playwright 页面上执行解析出的动作。"""
    el_map = {el["id"]: el for el in elements}
    try:
        if action_type == "click":
            target = el_map.get(arg1)
            if target and target["selector"]:
                page.click(target["selector"], timeout=3000)
            elif target and target["text"]:
                page.get_by_text(target["text"]).first.click(timeout=3000)
            else:
                # 遍历索引匹配
                selector = "button, input, a, select, textarea, [role='button'], [onclick]"
                loc = page.locator(selector).nth(arg1 - 1)
                loc.click(timeout=3000)
        elif action_type == "type":
            target = el_map.get(arg1)
            if target and target["selector"]:
                page.fill(target["selector"], arg2, timeout=3000)
            else:
                selector = "input, textarea"
                loc = page.locator(selector).nth(arg1 - 1)
                loc.fill(arg2, timeout=3000)
        elif action_type == "scroll":
            delta = 400 if arg1 == "down" else -400
            page.mouse.wheel(0, delta)
        elif action_type == "wait":
            time.sleep(1.0)
    except Exception as exc:
        return f"Action failed: {exc}"
    return None


def run_case(page, case, base_url, screenshots_dir, model=DEFAULT_MODEL, client=None):
    """对单条用例执行交互并判定结果。"""
    case_id = case["id"]
    task_desc = case["task"]
    expected_result = case["expected_result"]

    page.goto(base_url, timeout=10000, wait_until="domcontentloaded")
    time.sleep(0.5)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Task: {task_desc}\nExpected Result: {expected_result}\nPlease start testing."}
    ]

    saved_screenshots = []
    verdict = "NOT_DONE"
    reason = "Exceeded maximum steps without conclusion"

    for step in range(1, MAX_STEPS + 1):
        # 截图
        screenshot_bytes = page.screenshot(type="png")
        step_shot_name = f"{case_id}_step_{step}.png"
        step_shot_path = os.path.join(screenshots_dir, step_shot_name)
        with open(step_shot_path, "wb") as f:
            f.write(screenshot_bytes)
        saved_screenshots.append(step_shot_path)

        elements = get_interactive_elements(page)
        elements_text = format_elements(elements)

        base64_img = base64.b64encode(screenshot_bytes).decode("ascii")
        user_turn_content = [
            {"type": "text", "text": f"Step {step}/{MAX_STEPS}.\nInteractive elements:\n{elements_text}\nWhat is your next action?"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
        ]
        messages.append({"role": "user", "content": user_turn_content})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0
        )
        reply = response.choices[0].message.content or ""
        messages.append({"role": "assistant", "content": reply})

        action_type, arg1, arg2 = parse_action(reply)
        if action_type == "answer":
            verdict = arg1
            reason = arg2 or reply
            break

        err = execute_action(page, action_type, arg1, arg2, elements)
        time.sleep(0.5)
        if err:
            messages.append({"role": "user", "content": f"Observation: {err}"})

    # 保存最终截图
    final_shot_bytes = page.screenshot(type="png")
    final_shot_name = f"{case_id}_final.png"
    final_shot_path = os.path.join(screenshots_dir, final_shot_name)
    with open(final_shot_path, "wb") as f:
        f.write(final_shot_bytes)
    saved_screenshots.append(final_shot_path)

    if verdict == "YES":
        score = 1.0
        status = "passed"
    elif verdict == "PARTIAL":
        score = 0.5
        status = "wrong"
    elif verdict == "NO":
        score = 0.0
        status = "wrong"
    else:
        score = 0.0
        status = "not_done"

    return {
        "id": case_id,
        "requirement_id": case.get("requirement_id"),
        "name": case.get("name"),
        "score": score,
        "status": status,
        "verdict": verdict,
        "reason": reason,
        "screenshots": saved_screenshots,
    }


def run_ui_eval(base_url, cases, screenshots_dir, model=DEFAULT_MODEL):
    """启动浏览器对全部用例进行评分。"""
    from playwright.sync_api import sync_playwright
    import openai

    api_key = os.environ.get("YUDAO_EVAL_API_KEY")
    api_base = os.environ.get("YUDAO_EVAL_BASE_URL")
    if not api_key or not api_base:
        raise ValueError("Missing YUDAO_EVAL_API_KEY or YUDAO_EVAL_BASE_URL")

    client = openai.OpenAI(base_url=api_base, api_key=api_key)
    os.makedirs(screenshots_dir, exist_ok=True)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        for case in cases:
            res = run_case(page, case, base_url, screenshots_dir, model=model, client=client)
            results.append(res)

        browser.close()

    return results
