# 测试用的 MCP 服务器（stdio，官方 SDK 2.x 的 MCPServer 写的，工单 #69 的验收用）。
# 工具覆盖：文本、工具错误、协议错误（抛异常）、超时用的长等待、大结果、图像、结构化输出、
# 服务器自己起子进程（核对关闭与超时以后整个进程树都结束）、回报自己的环境变量与进程标识。
import json
import os
import subprocess
import sys
import time

from mcp.server.mcpserver import Image, MCPServer
from pydantic import BaseModel

server = MCPServer("yudao-test-stdio", version="0.0.1")


class Answer(BaseModel):
    answer: int

# 1x1 的 PNG：图像内容的验收只看类型与字节是否原样交出
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63"
    "0000010000010005000000010d0a2db40000000049454e44ae426082")
CHILDREN: list[subprocess.Popen] = []


@server.tool()
def echo(text: str) -> str:
    return text


@server.tool()
def failing_tool() -> str:
    raise ValueError("工具自己报告失败：EXPECTED_TOOL_ERROR")


@server.tool()
def slow(seconds: float) -> str:
    # 调用时限与取消的验收：这个工具一直等到被取消
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.05)
    return "done"


@server.tool()
def big(chars: int = 200_000) -> str:
    return "x" * chars


@server.tool()
def image() -> Image:
    return Image(data=PNG, format="png")


@server.tool(structured_output=True)
def structured(answer: int = 42) -> Answer:
    return Answer(answer=answer)


@server.tool()
def spawn_child() -> dict:
    # 起一个自己的子进程并一直留着：客户端关闭或超时以后整个进程树都应当结束
    child = subprocess.Popen([sys.executable, "-c", "import time\nwhile True: time.sleep(0.2)"])
    CHILDREN.append(child)
    return {"pid": child.pid}


@server.tool()
def child_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@server.tool()
def environment() -> dict:
    return {"env": dict(os.environ), "pid": os.getpid(), "executable": sys.executable}


@server.tool()
def crash() -> str:
    # 协议错误的验收：直接把错误写到标准错误并退出，客户端读到的原因里应当有末尾部分
    sys.stderr.write("服务器在协议错误以后退出：EXPECTED_CRASH\n")
    sys.stderr.flush()
    os._exit(7)


if __name__ == "__main__":
    print(json.dumps({"ready": True}), file=sys.stderr, flush=True)
    server.run("stdio")
