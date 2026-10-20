"""热点、共变与删掉的工作：只读 git 历史。

用法（仓库根）：uv run python docs/research/architecture-diagnosis-2026-10-19/hotspots.py [--since 2026-10-01] [--until <提交>]
- 热点：harness/ 下非测试文件，改动行数（增加加删除）乘以当前行数，取前 15。
- 共变：同一个提交里一起改的、属于不同顶层模块的非测试文件对，提交改动超过 40 个文件的不计（大的整理），取前 15。
- 删掉的工作：--diff-filter=D 删除的文件，按路径前缀与月份汇总删除时的行数。
main 上每个 PR 是一个压缩合并的提交，所以「同一提交」就是「同一 PR」。
"""
import collections
import itertools
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def code(path):
    return path.startswith("harness/") and path.endswith(".py") and "/tests/" not in path


def module(path):
    parts = path.split("/")
    return parts[1].removesuffix(".py") if len(parts) > 1 else path


def commits(since, until):
    out = git("log", "--no-merges", "--numstat", "--format=@@%h %ad", "--date=short",
              "--since", since, until)
    current = None
    for line in out.splitlines():
        if line.startswith("@@"):
            if current:
                yield current
            sha, date = line[2:].split(" ", 1)
            current = (sha, date, [])
        elif line.strip() and current:
            added, deleted, path = line.split("\t", 2)
            if "=>" in path:
                continue
            churn = (int(added) if added != "-" else 0) + (int(deleted) if deleted != "-" else 0)
            current[2].append((path, churn))
    if current:
        yield current


def main():
    since, until = arg("--since", "2026-05-01"), arg("--until", "HEAD")
    churn = collections.Counter()
    touches = collections.Counter()
    pairs = collections.Counter()
    for sha, date, files in commits(since, until):
        code_files = [p for p, _ in files if code(p)]
        for path, n in files:
            if code(path):
                churn[path] += n
                touches[path] += 1
        if len(files) > 40:
            continue
        for a, b in itertools.combinations(sorted(set(code_files)), 2):
            if module(a) != module(b):
                pairs[(a, b)] += 1
    print("## 热点（%s 至 %s；改动行数 × 当前行数）" % (since, until))
    rows = []
    for path, n in churn.items():
        try:
            size = len(git("show", "%s:%s" % (until, path)).splitlines())
        except subprocess.CalledProcessError:
            continue
        rows.append((n * size, path, n, size, touches[path]))
    for score, path, n, size, t in sorted(rows, reverse=True)[:15]:
        print("- %s：改动 %d 行 / %d 个提交，当前 %d 行" % (path, n, t, size))
    print("\n## 跨模块共变（同一提交一起改的次数）")
    for (a, b), n in pairs.most_common(15):
        print("- %d 次：%s + %s" % (n, a, b))
    print("\n## 删掉的工作（--diff-filter=D，删除时的行数）")
    deleted = collections.Counter()
    out = git("log", "--diff-filter=D", "--format=@@%h %ad", "--date=format:%Y-%m", "--name-only",
              "--since", since, until)
    month = sha = None
    for line in out.splitlines():
        if line.startswith("@@"):
            sha, month = line[2:].split(" ", 1)
        elif line.strip() and sha:
            try:
                size = len(git("show", "%s^:%s" % (sha, line)).splitlines())
            except subprocess.CalledProcessError:
                size = 0
            prefix = "/".join(line.split("/")[:2]) if line.startswith(("harness/", "client/", "docs/")) else line.split("/")[0]
            deleted[(month, prefix)] += size
    for (m, prefix), n in sorted(deleted.items(), key=lambda kv: (kv[0][0], -kv[1])):
        if n >= 500:
            print("- %s %s：%d 行" % (m, prefix, n))


if __name__ == "__main__":
    main()
