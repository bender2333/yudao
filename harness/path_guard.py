# 路径守卫（受控内核设计说明第 4.2 节，工单 #354）：采纳之前把交付相对基线的改动路径与运行实例的内核
# 清单比较，有交集时不自动采纳，由用户逐项批准。清单取自运行的实例（harness/definitions/kernel-manifest.json），
# 由用户所有，只由用户修改。
#
# 这个模块不是内核文件，也不在内核清单中：内核模块只导入内核文件、标准库与 pydantic，
# 清单的读取与差异的计算因此放在这里，由项目服务使用。

from __future__ import annotations

import difflib
import json
from pathlib import Path

from .public_tree import CapturedTree

# 运行实例的仓库根目录与内核清单：清单里的路径相对仓库根，glob 条目按这个目录展开
REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "harness" / "definitions" / "kernel-manifest.json"

# 清单里以 glob 形式登记的路径（内核测试、隐藏检查与参考解法），其余是逐个文件
def _is_glob(path: str) -> bool:
    return "*" in path

def kernel_manifest_paths() -> tuple[str, ...]:
    # 运行实例的内核清单里的全部路径：glob 条目按仓库当前的文件展开，逐个文件的条目原样保留。
    # 清单由 JSON 解析（重复的键不合法），条目缺少 path 时报错，不静默跳过
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    paths: list[str] = []
    for entry in document["paths"]:
        path = entry["path"]
        if _is_glob(path):
            paths.extend(sorted(str(item.relative_to(REPO_ROOT)).replace("\\", "/")
                                for item in REPO_ROOT.glob(path) if item.is_file()))
        else:
            paths.append(path)
    return tuple(paths)

def _matches(path: str, entry: str) -> bool:
    # 清单条目是逐个文件的路径时按相等比较；是 glob 时按登记处展开的同一套规则匹配
    if _is_glob(entry):
        return Path(path).match(entry)
    return path == entry

def kernel_hits(paths: list[str], manifest: tuple[str, ...]) -> list[str]:
    # 改动路径与内核清单的交集：按改动路径的顺序返回
    return [path for path in paths if any(_matches(path, entry) for entry in manifest)]

def _contents(tree: CapturedTree | None) -> dict[str, bytes]:
    return {} if tree is None else {item.path: item.data for item in tree.files}

def changed_paths(baseline: CapturedTree | None, delivery: CapturedTree) -> list[str]:
    # 交付相对基线的改动路径（新增、删除与内容变化），按路径排序；基线为空时全部文件都是新增
    before, after = _contents(baseline), _contents(delivery)
    return sorted({*before, *after} - {path for path in set(before) & set(after)
                                       if before[path] == after[path]})

def diff_text(path: str, before: bytes | None, after: bytes | None) -> str:
    # 一个改动路径的统一差异：新增与删除按空的一方计算
    def lines(data: bytes | None) -> list[str]:
        if data is None:
            return []
        try:
            return data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return [f"（这个路径不是 UTF-8 文本，无法按行比较：{len(data)} 字节）"]
    return "\n".join(difflib.unified_diff(lines(before), lines(after),
                                          fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""))

def kernel_diff(baseline: CapturedTree | None, delivery: CapturedTree, hits: list[str]) -> str:
    # 落在内核清单里的那些改动路径的差异全文，按路径顺序连接
    before, after = _contents(baseline), _contents(delivery)
    return "\n".join(diff_text(path, before.get(path), after.get(path)) for path in hits)
