"""工作区和 git 清单不一致时的行为：已跟踪但删掉的文件当作不存在，没 git add 的新文件不进索引。
用真实 git 的临时仓库，8 个读文件的命令都要跑。"""
import os

from conftest import git

SCRIPT = ".claude/skills/solo-worker/scripts/vision.mjs"  # 范围外的文件，被技能引用
UP = "docs/design/up.md"  # 范围内的文档，被另一份文档引用到小节
DOWN = "docs/design/down.md"


def prepare(scaffold_repo):
    scaffold_repo.write(UP, "# 上游\n\n## 细节\n\n上游的内容。\n")
    scaffold_repo.write(DOWN, "# 下游\n\n## 引用\n\n见 [上游](up.md)「细节」。\n")
    scaffold_repo.commit("上下游文档")
    scaffold_repo.cli("build")
    return scaffold_repo


def run_all(repo):
    """8 个命令都不能崩溃，返回各命令的输出。"""
    commands = {
        "build": ["build"],
        "status": ["status"],
        "who": ["who", "docs/agents/shared-rules.md"],
        "impact": ["impact", "docs/agents/shared-rules.md"],
        "scope": ["scope"],
        "pending": ["pending"],
        "view": ["view"],
        "check": ["check"],
    }
    return {name: repo.cli(*args)[1] for name, args in commands.items()}


def test_deleted_tracked_non_doc_is_dead_ref(scaffold_repo):
    repo = prepare(scaffold_repo)
    os.remove(repo.path / SCRIPT)
    assert SCRIPT in git(repo.path, "ls-files", "--deleted")
    outs = run_all(repo)
    assert "scripts/vision.mjs" in outs["check"] and "找不到" in outs["check"]


def test_deleted_tracked_doc_is_reported_everywhere(scaffold_repo):
    repo = prepare(scaffold_repo)
    os.remove(repo.path / UP)
    assert UP in git(repo.path, "ls-files", "--deleted")
    # 先不 build：status 和 pending 对着旧索引看到上游没了
    _, status = repo.cli("status")
    assert "删除  docs/design/up.md#上游 > 细节" in status
    _, pend = repo.cli("pending")
    assert "docs/design/down.md#下游 > 引用" in pend and "docs/design/up.md#上游 > 细节" in pend
    _, check = repo.cli("check")
    assert "docs/design/up.md#上游 > 细节 变了" in check
    run_all(repo)  # build 以后 8 个命令照样跑得通
    assert not (repo.path / ".doc-index/files" / (UP + ".json")).exists()


def test_untracked_new_doc_is_not_indexed(scaffold_repo):
    repo = prepare(scaffold_repo)
    repo.write("docs/design/new.md", "# 新文档\n\n见 `docs/agents/shared-rules.md`。\n")  # 不 git add
    run_all(repo)
    assert not (repo.path / ".doc-index/files/docs/design/new.md.json").exists()
    _, out = repo.cli("who", "docs/agents/shared-rules.md")
    assert "new.md" not in out
