# 发布检查（可信内核设计说明第 4.4 节，网页界面的提供与发布设计说明第 6.3 节，工单 #355）。
# 已安装的实例用它检查待发布的提交：用这一份实例的内核清单与检查，对待发布提交的内容做
#   1. 内核差异：上一次发布标签到待发布提交之间，内核清单里的路径有哪些改动，列进报告供用户查看，不算不通过
#      （阶段一由外部模型开发这个仓库，改内核路径不事前批准，守它的是 CI 里的内核测试；
#      运行中的系统改自己的内核才经决定请求「内核修改」批准，见可信内核设计说明第 3 节）；
#   2. 行数：内核清单里的 Python 文件的总行数不超过清单的上限；
#   3. 导入方向：内核清单里的模块只导入内核文件、标准库与 pydantic；
#   4. 评测专有内容：部门 Prompt、定义、工具说明、技能里出现评测场景专有内容即为不通过。
# 检查结果写进决定请求「实例升级」（目录流），由用户批准或拒绝；升级已安装的那一份是一次用户决定。
#
# 清单、上限与检查都取自运行的这一份实例：待发布提交里的清单与检查改不动这次的结果，
# 改清单是内核修改，本身要经决定请求「内核修改」由用户批准。

from __future__ import annotations

import ast
import fnmatch
import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pygit2

from .decisions import INSTANCE_UPGRADE
from .event_store import catalog_stream
from .models import CatalogEventType
from .write_path import NewCatalogEvent

# 内核清单在包内的位置；它在 wheel 中随包发布（pyproject.toml 的 package-data）
MANIFEST_PATH = Path(__file__).resolve().parent / "definitions" / "kernel-manifest.json"
# 上一次发布的标签的前缀（网页界面的提供与发布设计说明第 6.2 节）
TAG_PREFIX = "v"
# 允许的导入：内核文件、标准库与 pydantic（内核清单的 allowed_imports）
PYDANTIC_TOP = "pydantic"
# 评测场景材料的清单：专有内容标记只取自它给出的身份（标题与 source 里的编号、仓库与提交号）
EVAL_MANIFEST_TITLE = "title"
EVAL_MANIFEST_SOURCE_KEYS = ("record", "upstream_repository", "base_commit", "upstream_fix_commit", "version",
                              "dataset")
# 技能的定义目录：这一份实例的技能都在里面；目录不存在时这一处没有内容可检索
SKILLS_DIR = "skills"
# 少于这个长度的标记不做检索：太短的字串在定义里本来就会出现
MIN_TOKEN_LENGTH = 6


@dataclass(frozen=True)
class Finding:
    # 一项不通过：检查项、说明与位置
    check: str
    reason: str
    where: str


@dataclass(frozen=True)
class ReleaseCheckReport:
    # 一次发布检查的结果：被检查的提交与基准标签、四项检查的结论、是否通过，以及给人看的报告文本
    repository: str
    pending_commit: str
    base_tag: str | None
    kernel_changes: tuple[str, ...]
    kernel_python_lines: int
    python_lines_max: int
    findings: tuple[Finding, ...]
    text: str

    @property
    def passed(self) -> bool:
        return not self.findings


@dataclass(frozen=True)
class _Manifest:
    # 运行这一份实例的内核清单：模块路径、材料路径的匹配式、Python 行数上限与允许的导入
    modules: tuple[str, ...]
    material_globs: tuple[str, ...]
    python_lines_max: int
    allowed_imports: tuple[str, ...]


def load_manifest(path: Path = MANIFEST_PATH) -> _Manifest:
    # 读取内核清单。清单只由用户修改，缺少任何一个字段时这次检查无法进行，就地失败
    document = json.loads(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    materials: list[str] = []
    for entry in document["paths"]:
        if entry["kind"] == "module":
            modules.append(entry["path"])
        else:
            materials.append(entry["path"])
    return _Manifest(modules=tuple(modules), material_globs=tuple(materials),
                     python_lines_max=int(document["python_lines_max"]),
                     allowed_imports=tuple(document["allowed_imports"]))


def _is_material(path: str, manifest: _Manifest) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in manifest.material_globs)


def _is_kernel(path: str, manifest: _Manifest) -> bool:
    return path in manifest.modules or _is_material(path, manifest)



def _tree_entry(repository: pygit2.Repository, tree: pygit2.Tree, path: str) -> Any:
    # 按路径取待发布提交里的一条索引项；路径不存在时为空。路径以 / 分隔，逐级下到子树
    current = tree
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts):
        try:
            found = current[part]
        except KeyError:
            return None
        if index == len(parts) - 1:
            return found
        current = repository.get(found.id)
    return None


def _previous_tag(repository: pygit2.Repository) -> tuple[str, pygit2.Commit] | None:
    # 上一次发布的标签：名字以 v 开头、指向提交的标签中提交时间最晚的那一个；没有时为空。
    # 标签按提交时间排序，与发布的先后一致（设计说明第 6.2 节：标签 v<版本>）
    tagged: list[tuple[int, str, pygit2.Commit]] = []
    for reference in repository.references.objects:
        name = reference if isinstance(reference, str) else reference.name
        if not name.startswith("refs/tags/"):
            continue
        tag = name[len("refs/tags/"):]
        if not tag.startswith(TAG_PREFIX):
            continue
        target = repository.references[name].peel()
        if target is None or target.type != pygit2.enums.ObjectType.COMMIT:
            continue
        commit = repository.get(target.id)
        tagged.append((commit.commit_time, tag, commit))
    if not tagged:
        return None
    _, tag, commit = max(tagged, key=lambda item: item[0])
    return tag, commit


def _changed_paths(repository: pygit2.Repository, base: pygit2.Commit, pending: pygit2.Commit) -> tuple[str, ...]:
    # 两个提交之间改动的路径：重命名按改动后的路径记一次
    diff = repository.diff(base, pending)
    paths: list[str] = []
    for delta in diff.deltas:
        for path in (delta.old_file.path, delta.new_file.path):
            if path and path not in paths:
                paths.append(path)
    return tuple(sorted(paths))


def _kernel_imports(tree_source: str) -> list[tuple[int, str]]:
    # 一个内核模块导入的模块：按抽象语法树读出 import 与 from ... import 的目标，不执行被检查的代码
    module = ast.parse(tree_source)
    imported: list[tuple[int, str]] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                imported.append((node.lineno, node.module))
    return imported


def _import_allowed(name: str, manifest: _Manifest) -> bool:
    # 导入方向：内核文件、标准库与 pydantic。相对导入（from . import x）在 _kernel_imports 中不出现，
    # 它只指向同包内的模块，由调用方按内核文件判定
    top = name.split(".")[0]
    if top == PYDANTIC_TOP:
        return True
    if top == "harness":
        return _kernel_path_of(name, manifest) is not None
    return top in sys.stdlib_module_names or top == "__future__"


def _kernel_path_of(name: str, manifest: _Manifest) -> str | None:
    # 一个 harness.* 模块名对应的内核模块路径；不在清单里时为空
    for path in manifest.modules:
        if not path.endswith(".py"):
            continue
        parts = PurePosixPath(path).with_suffix("").parts
        if parts[0] != "harness":
            continue
        if name == ".".join(parts) or (len(parts) > 1 and name == ".".join(parts[:-1]) + "." + parts[-1]):
            return path
        if name == ".".join(parts[:-1]) and parts[-1] == "__init__":
            return path
    return None


def _eval_tokens(repository: pygit2.Repository, tree: pygit2.Tree) -> tuple[tuple[str, str], ...]:
    # 评测专有内容的标记：取自待发布仓库里评测场景材料的 manifest.json，是场景标题、记录编号、
    # 上游仓库与提交号这些只属于这个场景的身份，给出它们的来源便于在报告里写明命中了什么。
    tokens: set[tuple[str, str]] = set()
    try:
        scenarios = tree["evals"]["scenarios"]
    except KeyError:
        return ()
    for scenario in repository.get(scenarios.id):
        if scenario.type_str != "tree":
            continue
        try:
            manifest_entry = repository.get(scenario.id)["materials"]["manifest.json"]
        except KeyError:
            continue
        manifest = json.loads(entry_source(repository, manifest_entry))
        found = _tokens_of(manifest)
        tokens.update(found)
    return tuple(sorted(tokens))


def _tokens_of(manifest: dict[str, Any]) -> set[tuple[str, str]]:
    # 一份材料清单给出的专有内容标记：场景标题与 source 里的记录编号、上游仓库与提交号
    found: set[tuple[str, str]] = set()
    title = manifest.get(EVAL_MANIFEST_TITLE)
    if isinstance(title, str) and len(title) >= MIN_TOKEN_LENGTH:
        found.add((title, "场景标题"))
    source = manifest.get("source")
    if not isinstance(source, dict):
        return found
    for key in EVAL_MANIFEST_SOURCE_KEYS:
        value = source.get(key)
        if isinstance(value, str) and len(value) >= MIN_TOKEN_LENGTH:
            found.add((value, f"材料的 source.{key}"))
    return found


def _walk_tree(repository: pygit2.Repository, tree: pygit2.Tree, prefix: str) -> list[tuple[str, Any]]:
    # 列出一棵子树里的全部文件项，给出带目录的相对路径
    found: list[tuple[str, Any]] = []
    for entry in tree:
        path = f"{prefix}/{entry.name}"
        if entry.type_str == "tree":
            found.extend(_walk_tree(repository, repository.get(entry.id), path))
        else:
            found.append((path, entry))
    return found


def entry_source(repository: pygit2.Repository, entry: Any) -> str:
    return repository.get(entry.id).data.decode("utf-8", errors="replace")




def _department_prompts(repository: pygit2.Repository, tree: pygit2.Tree) -> list[tuple[str, str]]:
    # 部门 Prompt：角色定义里的 prompt，以及事项类型里各部门的 prompt
    surfaces: list[tuple[str, str]] = []
    for name in ("roles.json", "work_items.json"):
        entry = _tree_entry(repository, tree, f"harness/definitions/{name}")
        if entry is None:
            continue
        document = json.loads(entry_source(repository, entry))
        for item in document.get("roles", []) if isinstance(document, dict) else []:
            prompt = item.get("prompt")
            if isinstance(prompt, str) and prompt:
                surfaces.append((f"harness/definitions/{name} 角色 {item.get('id', '?')}", prompt))
        for item in document.get("work_items", []) if isinstance(document, dict) else []:
            for department in item.get("departments", []):
                prompt = department.get("prompt")
                if isinstance(prompt, str) and prompt:
                    surfaces.append((f"harness/definitions/{name} 事项 {item.get('id', '?')} "
                                     f"部门 {department.get('department', '?')}", prompt))
    return surfaces


def _definition_texts(repository: pygit2.Repository, tree: pygit2.Tree) -> list[tuple[str, str]]:
    # 定义：定义目录里的全部文件，整份文本都参与检索
    try:
        definitions = tree["harness"]["definitions"]
    except KeyError:
        return []
    return [(path, entry_source(repository, entry))
            for path, entry in _walk_tree(repository, repository.get(definitions.id), "harness/definitions")]


def _tool_descriptions(repository: pygit2.Repository, tree: pygit2.Tree) -> list[tuple[str, str]]:
    # 工具说明：工具定义里的 description
    entry = _tree_entry(repository, tree, "harness/definitions/tools.json")
    if entry is None:
        return []
    document = json.loads(entry_source(repository, entry))
    surfaces: list[tuple[str, str]] = []
    items = document.get("tools", []) if isinstance(document, dict) else []
    for item in items:
        description = item.get("description")
        if isinstance(description, str) and description:
            surfaces.append((f"harness/definitions/tools.json 工具 {item.get('name', '?')}", description))
    return surfaces


def _skill_texts(repository: pygit2.Repository, tree: pygit2.Tree) -> list[tuple[str, str]]:
    # 技能：仓库下的技能目录里的全部文件；目录不存在时这一处没有内容
    try:
        skills = tree[SKILLS_DIR]
    except KeyError:
        return []
    return [(path, entry_source(repository, entry))
            for path, entry in _walk_tree(repository, repository.get(skills.id), SKILLS_DIR)]


def _proprietary_findings(repository: pygit2.Repository, tree: pygit2.Tree,
                          tokens: tuple[tuple[str, str], ...]) -> list[Finding]:
    # 评测专有内容的检索：四处表面里出现评测材料专有的内容就是不通过，位置写明表面与命中的标记
    if not tokens:
        return []
    findings: list[Finding] = []
    for surface, sources in (("部门 Prompt", _department_prompts(repository, tree)),
                             ("定义", _definition_texts(repository, tree)),
                             ("工具说明", _tool_descriptions(repository, tree)),
                             ("技能", _skill_texts(repository, tree))):
        for where, text in sources:
            for token, origin in tokens:
                if token in text:
                    findings.append(Finding("评测专有内容", f"{surface}里出现评测场景专有内容：{token}（{origin}）",
                                            where))
    return findings


def check_repository(repo_root: Path, manifest: _Manifest | None = None) -> ReleaseCheckReport:
    # 对仓库的待发布提交（HEAD）运行发布检查：基准是上一次发布的标签，没有标签时基准为空，
    # 全部内核路径都算作改动。清单不给时取运行这一份实例的清单
    manifest = manifest or load_manifest()
    repository = pygit2.Repository(str(repo_root))
    pending = repository.revparse_single("HEAD").peel(pygit2.Commit)
    tree = pending.tree
    previous = _previous_tag(repository)
    base_tag, base_commit = (None, None) if previous is None else previous
    changed = (() if base_commit is None else
               _changed_paths(repository, base_commit, pending))
    kernel_changes = tuple(path for path in changed if _is_kernel(path, manifest))
    if base_commit is None:
        kernel_changes = tuple(path for path in (manifest.modules + manifest.material_globs)
                               if _tree_entry(repository, tree, path) is not None)

    findings: list[Finding] = []

    lines = 0
    for path in manifest.modules:
        entry = _tree_entry(repository, tree, path)
        if entry is None:
            findings.append(Finding("行数", "内核清单里的模块在待发布提交中不存在", path))
            continue
        source = entry_source(repository, entry)
        lines += len(source.splitlines())
        for number, name in _kernel_imports(source):
            if not _import_allowed(name, manifest):
                findings.append(Finding("导入方向", f"导入了不允许的模块 {name}", f"{path}:{number}"))
    if lines > manifest.python_lines_max:
        findings.append(Finding("行数", f"内核 Python 总行数 {lines} 超过清单上限 {manifest.python_lines_max}",
                                "内核清单的 python_lines_max"))

    findings += _proprietary_findings(repository, tree, _eval_tokens(repository, tree))

    return ReleaseCheckReport(
        repository=str(repo_root), pending_commit=str(pending.id), base_tag=base_tag,
        kernel_changes=kernel_changes, kernel_python_lines=lines, python_lines_max=manifest.python_lines_max,
        findings=tuple(findings), text=report_text(
            repository=str(repo_root), pending_commit=str(pending.id), base_tag=base_tag,
            kernel_changes=kernel_changes, kernel_python_lines=lines, python_lines_max=manifest.python_lines_max,
            findings=tuple(findings),
        ),
    )


def report_text(*, repository: str, pending_commit: str, base_tag: str | None, kernel_changes: tuple[str, ...],
                kernel_python_lines: int, python_lines_max: int, findings: tuple[Finding, ...]) -> str:
    # 给人看的报告：结论、基准与待发布提交、四项检查的结果，不通过时逐项写明位置
    lines = [f"发布检查：{'通过' if not findings else '不通过'}",
             f"仓库：{repository}",
             f"待发布提交：{pending_commit[:12]}",
             f"基准标签：{base_tag or '无（第一个发布）'}",
             f"内核路径改动：{'、'.join(kernel_changes) if kernel_changes else '无'}",
             f"内核 Python 行数：{kernel_python_lines}（上限 {python_lines_max}）"]
    if findings:
        lines.append("不通过项：")
        lines += [f"  [{item.check}] {item.where}：{item.reason}" for item in findings]
    else:
        lines.append("三项检查（行数、导入方向、评测专有内容）全部通过；内核路径改动列在上面，供用户查看。")
    return "\n".join(lines)


def decision_request_payload(report: ReleaseCheckReport) -> dict[str, object]:
    # 决定请求「实例升级」的载荷：选项是批准升级与拒绝，材料是发布检查的结果
    return {
        "kind": INSTANCE_UPGRADE.name,
        "blocks": INSTANCE_UPGRADE.blocks,
        "options": [{"id": option.id, "label": option.label} for option in INSTANCE_UPGRADE.options],
        "description": ("发布检查" + ("通过" if report.passed else "不通过") + "：是否把这台电脑上安装的那一份"
                        f"升级到提交 {report.pending_commit[:12]}？"),
        "facts": [report.text],
        "report": {
            "repository": report.repository, "pending_commit": report.pending_commit, "base_tag": report.base_tag,
            "kernel_changes": list(report.kernel_changes), "kernel_python_lines": report.kernel_python_lines,
            "python_lines_max": report.python_lines_max, "passed": report.passed,
            "findings": [{"check": item.check, "reason": item.reason, "where": item.where}
                         for item in report.findings],
        },
    }

def request_instance_upgrade(system: Any, report: ReleaseCheckReport) -> str:
    # 把发布检查的结果写进目录流中的决定请求「实例升级」，返回请求的编号。
    # 检查不通过也写入：用户看到的是不通过的结果，批准与拒绝都由用户决定
    payload = decision_request_payload(report)

    def decide(transaction: Any) -> list[Any]:
        return transaction.append(NewCatalogEvent(CatalogEventType.INSTANCE_UPGRADE_REQUESTED, payload,
                                                  actor="system"))

    events = system.writes.transact(catalog_stream(), decide)
    return events[0].event_id
