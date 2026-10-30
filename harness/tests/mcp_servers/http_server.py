# 测试用的 MCP 服务器（streamable HTTP，官方 SDK 2.x 的 MCPServer 写的，工单 #69 的验收用）。
# 端口由命令行给出，路径是 SDK 默认的 /mcp；就绪以后往标准错误写一行，测试按端口等到能连接再开始。
import sys
import time

from mcp.server.mcpserver import MCPServer

server = MCPServer("yudao-test-http", version="0.0.1")


@server.tool()
def echo(text: str) -> str:
    return text


@server.tool()
def slow(seconds: float) -> str:
    # 调用时限与取消的验收：一直等到被取消
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.05)
    return "done"


if __name__ == "__main__":
    port = int(sys.argv[1])
    print(f"listening on 127.0.0.1:{port}", file=sys.stderr, flush=True)
    server.run("streamable-http", host="127.0.0.1", port=port)
