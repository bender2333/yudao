# 内核清单本身的两项检查（可信内核设计说明第 3 节）：
# 1. 内核模块只导入内核模块、标准库与 pydantic；
# 2. 内核模块的总行数不超过清单里的上限。
#
# 清单是数据，由用户所有；这两项检查按清单里 kind 为 module 的条目判定，
# kind 为 material 的条目（内核自己的测试、评测材料、发布脚本与基础规则文本）由路径守卫保护，
# 不参加这两项检查——测试要导入 pytest，评分器按场景运行，文档与发布脚本不是裁决模块。
# 读仓库里的静态文件，不开数据库、不用子进程、不用网络，属于单元层。

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "harness" / "definitions" / "kernel-manifest.json"

# 清单里以 glob 形式登记的路径（隐藏检查与参考解法按场景名展开），其余是逐个文件
def _is_glob(path: str) -> bool:
    return "*" in path


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _modules(manifest: dict) -> list[str]:
    # 内核的 Python 模块：清单里 kind 为 module 的文件。两项检查只按它们判定。
    return [entry["path"] for entry in manifest["paths"]
            if entry["kind"] == "module" and entry["path"].endswith(".py") and (REPO_ROOT / entry["path"]).exists()]


def _module_of(relative: str) -> str:
    stem = relative[len("harness/"):]
    if stem.endswith("/__init__.py"):
        return "harness." + stem[: -len("/__init__.py")].replace("/", ".")
    return "harness." + stem[: -len(".py")].replace("/", ".")


def _package_of(relative: str) -> str:
    module = _module_of(relative)
    return module if relative.endswith("/__init__.py") else module.rsplit(".", 1)[0]


def _resolve(module: str) -> str | None:
    relative = module[len("harness."):] if module.startswith("harness.") else module
    for candidate in (relative + ".py", relative + "/__init__.py"):
        path = "harness/" + candidate
        if (REPO_ROOT / path).exists():
            return path
    return None


def _imported_modules(relative: str) -> list[tuple[int, str]]:
    # 文件里的导入语句按模块名给出，不执行任何代码
    package = _package_of(relative)
    found = []
    for node in ast.walk(ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                up = node.level - 1
                base = ".".join(parts[:len(parts) - up]) if up else parts[0]
                found.append((node.lineno, f"{base}.{node.module}" if node.module else base))
            else:
                found.append((node.lineno, node.module or ""))
    return found


def test_the_manifest_lists_paths_with_a_reason_each():
    manifest = _manifest()
    assert manifest["owner"] == "user"
    entries = manifest["paths"]
    assert entries, "内核清单没有登记路径"
    for entry in entries:
        assert entry["why"].strip(), f"{entry['path']} 没有写明为什么属于内核"
        assert entry["kind"] in manifest["kinds"], f"{entry['path']} 的 kind 不在 kinds 的说明里"
        if not _is_glob(entry["path"]):
            assert (REPO_ROOT / entry["path"]).exists(), f"{entry['path']} 在清单里但仓库里没有这个文件"
    # 六条基础规则与四个探针
    assert len(manifest["rules"]) == 6
    assert [rule["rule"] for rule in manifest["rules"]] == [
        "事实只经写入口写入",
        "每个工具开始事件之前有一条允许的许可记录",
        "每个 run 以封闭清单里的原因结束或进入等待",
        "已用的时间与次数跨重启连续",
        "验证者提交独立判断之前看不到作者的解释",
        "未校准的判定点不改变事实事件",
    ]
    for rule in manifest["rules"]:
        assert rule["added_by"].strip(), f"{rule['test']} 没有写明由哪一项加入"
    assert [probe["name"] for probe in manifest["probes"]] == [
        "reference_passes_all", "seeded_defect_fails", "out_of_scope_write_denied", "false_release_reported",
    ]
    for probe in manifest["probes"]:
        assert probe["expect"].strip(), f"探针 {probe['name']} 没有写明期望结果"


def test_every_rule_already_in_place_names_a_test_that_exists():
    # 每条基础规则在清单里有一行说明与一个测试名称。第五条随先判断后看解释的工单加入，
    # 第六条随 Stage 5 的判定点工单加入；还没有加入的两条只核对清单写明了由哪一项加入。
    manifest = _manifest()
    for rule in manifest["rules"]:
        if rule.get("ready"):
            relative = "harness/tests/" + rule["test"]
            assert (REPO_ROOT / relative).exists(), f"{rule['rule']} 对应的测试 {rule['test']} 不存在"
        else:
            assert not (REPO_ROOT / ("harness/tests/" + rule["test"])).exists(), \
                f"{rule['test']} 已经存在，清单里的 {rule['added_by']!r} 需要更新"


def test_kernel_files_import_only_kernel_files_stdlib_and_pydantic():
    manifest = _manifest()
    kernel = set(_modules(manifest))
    offenders = []
    for relative in sorted(kernel):
        for line, module in _imported_modules(relative):
            top = module.split(".")[0]
            if top == "harness":
                resolved = _resolve(module)
                assert resolved is not None, f"{relative}:{line} 导入了仓库里没有的模块 {module}"
                if resolved not in kernel:
                    offenders.append((relative, line, module, resolved))
            elif top not in sys.stdlib_module_names and module != "__future__" and top != "pydantic":
                offenders.append((relative, line, module, "不是内核文件、标准库或 pydantic"))
    assert offenders == [], f"内核文件导入了清单以外的模块：{offenders}"


def test_kernel_python_lines_stay_within_the_manifest_cap():
    manifest = _manifest()
    kernel = _modules(manifest)
    counts = {relative: len((REPO_ROOT / relative).read_text(encoding="utf-8").splitlines())
              for relative in kernel}
    total = sum(counts.values())
    assert total <= manifest["python_lines_max"], (
        f"内核 Python 文件共 {total} 行，超过清单上限 {manifest['python_lines_max']} 行；"
        f"按文件的行数：{counts}"
    )