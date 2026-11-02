import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent
REAL_REPO = TOOL.parent.parent

ROLES_TABLE = """| 角色 | 做什么 | 不做什么 |
| --- | --- | --- |
| 用户 | 定走向 | 不写代码 |
| 总架构师 | 总图 | 不管工单 |
| 子架构师 | 模块 | 不改总图 |
| 架构师循环 | 用户不在时 | 不改规则 |
| solo 执行者 | 实现 | 不改总图 |
| 审查者 | 审查 | 不推送 |
| agent 试用者 | 试用 | 不建工单 |
"""


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=测试", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")


class Repo:
    """临时的真实 git 仓库。"""

    def __init__(self, path):
        self.path = Path(path)
        git(self.path, "init", "-q", "-b", "main")

    def write(self, rel, text, newline="\n"):
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)

    def read(self, rel):
        return (self.path / rel).read_text(encoding="utf-8")

    def commit(self, message="提交"):
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "-m", message)

    def cli(self, *args, check=True):
        r = subprocess.run(
            [sys.executable, "-m", "doc_consistency", "--root", str(self.path), *args],
            cwd=TOOL,
            capture_output=True,
        )
        out = r.stdout.decode("utf-8") + r.stderr.decode("utf-8")
        if check:
            assert r.returncode == 0, out
        return r.returncode, out

    def index_snapshot(self):
        base = self.path / ".doc-index"
        return {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}

    def write_labels(self, names):
        self.write(".doc-index/labels.json", json.dumps({"source": "gh label list", "labels": sorted(names)}, ensure_ascii=False))


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


@pytest.fixture
def docs_repo(repo):
    """设计文档一侧：真实的总图，加几份引用它的文档。"""
    repo.write("docs/architecture.html", (REAL_REPO / "docs" / "architecture.html").read_text(encoding="utf-8"))
    repo.write(
        "docs/design/context.md",
        "# 上下文设计\n\n总图位置：第四节「装配」缝。依据：无\n\n## 方案\n\n见 [另一份](other.md)「细节」，也见 `docs/design/other.md`。\n",
    )
    repo.write(
        "docs/design/other.md",
        "# 另一份\n\n## 细节\n\n第一处细节。\n\n## 细节\n\n同名小节的内容。\n",
    )
    repo.commit("文档")
    return repo


@pytest.fixture
def scaffold_repo(repo):
    """脚手架一侧：满足 data/roles.json 的最小规则文件、技能与工作流表格。"""
    repo.write(".gitignore", ".tmp/\n")
    repo.write(
        "docs/agents/workflow.md",
        "# 工作方式\n\n## 2. 角色\n\n" + ROLES_TABLE + "\n## 4. 状态与标签\n\n"
        "| 状态 | 意思 |\n| --- | --- |\n| `needs-triage` | 交回架构师 |\n| `waiting` | 在等前提 |\n\n"
        "## 9. 技能\n\n| 技能 | 管什么 |\n| --- | --- |\n| `solo-worker` | 做工单 |\n| `ghost-skill` | 不存在的技能 |\n",
    )
    repo.write(
        "CLAUDE.md",
        "# 适用范围\n\n共同遵守的内容在 [shared-rules](docs/agents/shared-rules.md)，与本文件一起读。\n"
        "用 `/loop` 轮询，用 `/solo-worker` 做工单，也有 `/ghost`。见 `docs/agents/missing.md` 与 `harness/tests/test_nope.py`。\n"
        "运行产物放 `.tmp/out.json`。标签：`needs-triage`、`no-such-label`。\n"
        "取回附件：`gh run download 1 -n integration-results`。\n"
        "没有工单编号的日记写在 `agents_jour/其他.md`，别的日记 `agents_jour/别的.md` 不在约定清单里。\n",
    )
    repo.write(
        "AGENTS.md",
        "# 适用范围\n\n角色的做法在技能里：solo 执行者读 `.claude/skills/solo-worker/SKILL.md`，"
        "审查者读 `.claude/skills/reviewer/SKILL.md`。命令见 [另一份](docs/agents/other.md)。\n"
        "共同遵守的内容在 [shared-rules](docs/agents/shared-rules.md)，与本文件一起读。\n",
    )
    repo.write("docs/agents/shared-rules.md", "# 共同规则\n\n共同规则的内容。\n")
    repo.write("docs/agents/other.md", "# 另一份\n\n只是被提到的文件。\n")
    for name in ("next", "reviewer", "trial"):
        repo.write(f".claude/skills/{name}/SKILL.md", f"---\nname: {name}\n---\n\n# {name}\n\n内容。\n")
    repo.write(
        ".claude/skills/solo-worker/SKILL.md",
        "---\nname: solo-worker\n---\n\n# solo 工人\n\n运行 `scripts/vision.mjs`，流程见 [工作方式](../../../docs/agents/workflow.md)。遇到问题加 `needs-triage`。\n",
    )
    repo.write(".claude/skills/solo-worker/scripts/vision.mjs", "export {};\n")
    repo.write(
        "docs/agents/mentions-waiting.md",
        "# 只提到等待\n\n工单在 `waiting` 状态时先不领。\n",
    )
    repo.write_labels(["needs-triage", "waiting", "ready-for-agent"])
    repo.commit("脚手架")
    return repo
