# 找 Playwright MCP 的程序位置（浏览器与 computer use 设计说明「执行位置上的程序」、「运行方式」；工单 #1184）。
#
# 全局安装的位置不能只按目录猜：CI 的集成层用 `npm install --global @playwright/mcp@0.0.83` 装，
# GitHub Actions 的 Windows 宿主把全局前缀放在 `C:\npm\prefix`，不在 `%APPDATA%\npm`，按目录猜会漏掉它，
# 六条浏览器集成用例在那里以「was not found」失败（分支集成层 41760615422）。所以先问 npm 自己的
# 全局根目录，再按 node 与 npm 所在的目录兜底。这里只调纯函数，不起进程、不读临时目录，属于单元层。

from pathlib import Path

from harness.browser import _node_module_roots


def test_the_global_install_is_looked_up_at_the_npm_reported_root_first():
    # npm 报出的全局根目录最可信：它有结果时排在候选的第一位；node 与 npm 所在的目录各算一处
    roots = _node_module_roots("/usr/local/bin/node", "/usr/local/bin/npm", Path("/opt/npm/lib/node_modules"))
    assert roots[0] == Path("/opt/npm/lib/node_modules")
    assert Path("/usr/local/bin/node_modules") in roots


def test_the_layout_of_a_windows_runner_is_found_through_the_node_directory():
    # GitHub Actions 的 Windows 宿主：node 与全局前缀在一起（C:\npm\prefix\node.exe，
    # 全局包装在 C:\npm\prefix\node_modules），npm root -g 问不出来时按 node 的位置找得到
    roots = _node_module_roots("C:/npm/prefix/node.exe", "C:/npm/prefix/npm.cmd", None)
    assert Path("C:/npm/prefix/node_modules") in roots
    cli = Path("C:/npm/prefix/node_modules") / "@playwright" / "mcp" / "cli.js"
    assert cli.name == "cli.js" and cli.parent.parent.name == "@playwright"


def test_node_and_npm_in_the_same_directory_are_listed_once():
    # 两台程序装在同一目录时那一处只列一次：候选清单按可信程度排，重复的没有意义
    roots = _node_module_roots("C:/tools/node.exe", "C:/tools/npm.cmd", None)
    assert roots.count(Path("C:/tools/node_modules")) == 1
