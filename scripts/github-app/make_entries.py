# 生成 gh.exe 与 git.exe 两个入口（工单 #526）。
#
# 入口是 distlib 的 Windows 启动器（pip 生成命令行入口用的同一个），后面接一个 zip，
# zip 里的 __main__.py 只把入口名与参数交给同目录的 yudao_github_app.py。
# 启动器用 CreateProcess 直接启动 python，参数不经过 cmd 重新解析，
# | & ^ ( ) % ! 引号、空格与中文原样到达；cmd、PowerShell、Git bash 与 gh 调用 git 都命中 .exe。
# 解释器写成 /usr/bin/env python，取 PATH 上第一个 python，入口文件与机器无关，可以提交。
# zip 的时间戳固定，同一个 distlib 版本生成的字节相同，测试据此核对提交的入口。
#
# 用法：uv run python scripts/github-app/make_entries.py [目标目录，默认本目录]

import os
import sys
from pathlib import Path

from distlib.scripts import ScriptMaker

ENTRY_NAMES = ("gh", "git")

ENTRY_SCRIPT = """import runpy
import sys
from pathlib import Path

entry = Path(sys.argv[0]).resolve()
module = entry.with_name("yudao_github_app.py")
sys.argv = [str(module), entry.stem, *sys.argv[1:]]
runpy.run_path(str(module), run_name="__main__")
"""

def make_entries(target: Path) -> list[str]:
    # distlib 按 SOURCE_DATE_EPOCH 写 zip 的时间戳；1980-01-01 是 zip 能表示的最早时刻
    os.environ["SOURCE_DATE_EPOCH"] = "315532800"
    maker = ScriptMaker(None, str(target))
    maker.executable = "/usr/bin/env python"
    maker.script_template = ENTRY_SCRIPT
    maker.variants = {""}
    maker.clobber = True
    return maker.make_multiple([f"{name} = yudao_github_app:main" for name in ENTRY_NAMES])

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    for written in make_entries(target):
        print(written)
