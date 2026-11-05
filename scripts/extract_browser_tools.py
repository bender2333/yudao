# 浏览器工具定义的提取脚本（浏览器与 computer use 设计说明第 4.1、4.2 节，工单 #147）。
#
# 浏览器工具的定义由 Playwright MCP 固定版本的 tools/list 生成，写进 harness/definitions/browser_tools.json，
# 随 Yudao 发布；升级 Playwright MCP 时同时更新设计说明第 3.2 节的版本与这份生成的定义。
#
# 用法（仓库根目录）：
#   uv run python scripts/extract_browser_tools.py --record      # 起真实的 Playwright MCP，记下 tools/list 的回复
#   uv run python scripts/extract_browser_tools.py --write       # 按记下的回复生成定义
#   uv run python scripts/extract_browser_tools.py               # 只核对提交的定义与记下的回复一致
#
# --record 直接对真实的 Playwright MCP 0.0.83 说话，不用 mock；记下的回复随仓库提交
# （harness/tests/data/playwright_mcp_tools_list.json），测试读它核对提交的定义，不需要网络与 node。
# 筛选与映射在 harness/tools.py 的 browser_tool_definitions：哪些工具提供、不提供哪两个、动作类别、
# 恢复契约与是否需要图像输入都写在那里，这个脚本只负责取回复与读写文件。

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from harness.tools import BROWSER_TOOL_NAMES, EXCLUDED_BROWSER_TOOLS, browser_tool_definitions  # noqa: E402

PACKAGE = "@playwright/mcp@0.0.83"
RECORDED_PATH = REPO_ROOT / "harness" / "tests" / "data" / "playwright_mcp_tools_list.json"
OUTPUT_PATH = REPO_ROOT / "harness" / "definitions" / "browser_tools.json"
# 设计说明第 4.1 节的启动参数：Chromium、无头、隔离、与屏幕工具相同的视口、启用断言工具、
# 截图以图像内容返回、每个动作带完整的可访问性结构
LAUNCH_ARGS = ["--browser", "chromium", "--headless", "--isolated", "--viewport-size", "1280x800",
               "--caps", "testing", "--image-responses", "allow", "--snapshot-mode", "full"]


def record_tools_list(timeout_sec: float = 180.0) -> dict[str, Any]:
    # 起真实的 Playwright MCP（stdio），初始化以后要 tools/list 的回复；不打开浏览器页面
    command = ["npx", "--yes", PACKAGE, *LAUNCH_ARGS]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", shell=True)
    try:
        def send(message: dict[str, Any]) -> None:
            assert process.stdin is not None
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def wait_for(request_id: int) -> dict[str, Any] | None:
            assert process.stdout is not None
            while True:
                line = process.stdout.readline()
                if not line:
                    return None
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "yudao-extract-browser-tools", "version": "1"}}})
        if wait_for(1) is None:
            raise RuntimeError("the Playwright MCP server did not answer initialize")
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        response = wait_for(2)
        if response is None:
            raise RuntimeError("the Playwright MCP server did not answer tools/list")
        return response
    finally:
        process.kill()


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
                    encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the browser tool definitions from Playwright MCP tools/list")
    parser.add_argument("--record", action="store_true", help="ask the real Playwright MCP and save its tools/list reply")
    parser.add_argument("--write", action="store_true", help="write the generated definitions")
    parser.add_argument("--recorded", type=Path, default=RECORDED_PATH, help="recorded tools/list reply")
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH, help="generated definitions file")
    arguments = parser.parse_args(argv)

    if arguments.record:
        response = record_tools_list()
        write_json(arguments.recorded, response)
        print(f"记下了 {len(response['result']['tools'])} 个工具的 tools/list 回复：{arguments.recorded}")
        return 0

    response = json.loads(arguments.recorded.read_text(encoding="utf-8"))
    definitions = browser_tool_definitions(response)
    listed = {str(tool.get("name")) for tool in response["result"]["tools"]}
    missing = [name for name in BROWSER_TOOL_NAMES if name not in listed]
    if missing:
        raise SystemExit(f"记下的回复里没有这些工具：{', '.join(missing)}")
    skipped = sorted(listed - set(BROWSER_TOOL_NAMES) - set(EXCLUDED_BROWSER_TOOLS))
    if skipped:
        raise SystemExit(f"记下的回复里有既没有提供也没有排除的工具：{', '.join(skipped)}")

    if arguments.write:
        write_json(arguments.out, definitions)
        print(f"写出了 {len(definitions)} 个浏览器工具的定义：{arguments.out}")
        return 0

    committed = json.loads(arguments.out.read_text(encoding="utf-8"))
    if committed != definitions:
        changed = sorted(set(committed) ^ set(definitions)) or sorted(
            name for name in definitions if committed.get(name) != definitions[name])
        print("提交的定义与记下的回复生成的不一致：" + "、".join(changed))
        return 1
    print(f"提交的 {len(definitions)} 个浏览器工具的定义与记下的回复一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
