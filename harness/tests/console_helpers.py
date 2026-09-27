import io
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from contextlib import redirect_stdout
from http.client import HTTPConnection
from urllib.parse import urlsplit

from harness.__main__ import main

# 控制台的启动测试：在测试的主线程中运行命令行入口 main(argv)，与 python -m harness 走同一条路径，
# 经 HTTP 核对控制台，再像在终端按下 Ctrl+C 一样停止它。默认的数据目录、模型目录与凭据文件都是相对当前目录的路径，
# 调用方先把当前目录切换到测试目录；端口写 0，由系统分配空闲端口，地址取自控制台打印的那一行

CONSOLE_LINE = "Yudao console "
# 控制台开始回答 /api/health 的等待上限，只用来防止测试一直等待
STARTUP_TIMEOUT_SEC = 120


def accepts_connections(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def run_console(argv: list[str], check: Callable[[str, int], None]) -> int:
    # 控制台打印地址并回答 /api/health 以后，另一个线程执行 check(host, port)，然后向本进程发送 SIGINT，
    # 主线程中的控制台收到 KeyboardInterrupt 后停止，main 返回。返回 main 的退出码；check 的异常在 main 返回以后抛出
    assert threading.current_thread() is threading.main_thread(), "SIGINT 只在主线程中处理"
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler, "SIGINT 需要按默认方式变为 KeyboardInterrupt"
    output = _ConsoleOutput(sys.stdout)
    finished = threading.Event()
    failure: list[BaseException] = []

    def interrupt() -> None:
        if not finished.is_set():
            signal.raise_signal(signal.SIGINT)

    def watch() -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
        while True:
            if finished.is_set():
                return
            address = output.address()
            # 回答了 /api/health 说明主线程已经在 serve_forever 中接收连接
            if address is not None and _answers_health(*address):
                break
            if time.monotonic() > deadline:
                failure.append(TimeoutError("console did not start serving"))
                interrupt()
                return
            time.sleep(0.05)
        try:
            check(*address)
        except BaseException as exc:
            failure.append(exc)
        finally:
            interrupt()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        with redirect_stdout(output):
            code = main(argv)
    except KeyboardInterrupt:
        # 控制台没有在等待上限内开始回答时，SIGINT 在启动过程中到达
        if not failure:
            raise
        code = 1
    finally:
        finished.set()
        watcher.join()
    if failure:
        raise failure[0]
    return code


class _ConsoleOutput(io.TextIOBase):
    # main 的标准输出照常写到原来的位置，同时记下控制台打印的地址
    def __init__(self, target: io.TextIOBase) -> None:
        self._target = target
        self._text = ""
        self._address: tuple[str, int] | None = None
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        self._target.write(text)
        with self._lock:
            self._text += text
            for line in self._text.splitlines():
                if line.startswith(CONSOLE_LINE):
                    url = urlsplit(line.removeprefix(CONSOLE_LINE).strip())
                    self._address = (url.hostname, url.port)
        return len(text)

    def flush(self) -> None:
        self._target.flush()

    def address(self) -> tuple[str, int] | None:
        with self._lock:
            return self._address


def _answers_health(host: str, port: int) -> bool:
    connection = HTTPConnection(host, port, timeout=2)
    try:
        connection.request("GET", "/api/health")
        return connection.getresponse().status == 200
    except OSError:
        return False
    finally:
        connection.close()
