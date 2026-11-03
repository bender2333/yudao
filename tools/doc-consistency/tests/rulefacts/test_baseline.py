"""规则事实线第 6 步：基线。记录以后 check 的新提醒为 0；改一句后重新报；两次运行一致；只追加。"""

import re

from test_patterns import RESTATE, restate, rich
from test_rulefacts import rf_repo  # noqa: F401

from doc_consistency.rulefacts import baseline

BASE = ".doc-index/rulefacts/baseline.jsonl"
# 像规则又不合句式的话（键不在词表里）：三句，各自是一条提醒
NOISE = ["第1号文件由执行者加上", "第2号文件由执行者加上", "第3号文件由执行者加上"]


def counts(out):
    m = re.search(r"== 像在说规则但解析不了：基线 (\d+) 条，新 (\d+) 条", out)
    assert m, out
    return int(m.group(1)), int(m.group(2))


def listed(out):
    """提醒区里列出的句子行（`文件:行  [标签]  句子`）。"""
    tail = out.replace("\r\n", "\n").split("== 像在说规则但解析不了：")[1].split("\n")[1:]
    return [ln for ln in tail if re.match(r"\S+:\d+  \[", ln)]


def test_check_before_baseline_reports_everything_as_new(rf_repo):
    restate(rich(rf_repo), *NOISE)
    _, out = rf_repo.cli("rules", "check")
    base, new = counts(out)
    assert base == 0 and new >= 3 and sum(RESTATE in ln for ln in listed(out)) == 3
    assert not (rf_repo.path / BASE).exists()


def test_after_baseline_check_reports_no_new_and_all_lists_them_marked(rf_repo):
    restate(rich(rf_repo), *NOISE)
    rc, out = rf_repo.cli("rules", "baseline")
    assert rc == 0 and "基线已更新：原有 0 条，新增" in out
    _, out = rf_repo.cli("rules", "check")
    base, new = counts(out)
    assert new == 0 and base >= 3 and listed(out) == []
    _, out = rf_repo.cli("rules", "check", "--all")
    marked = [ln for ln in listed(out) if "[基线，" in ln]
    assert counts(out) == (base, 0) and len(marked) == base and sum(RESTATE in ln for ln in marked) == 3


def test_changing_one_sentence_reports_it_again_and_only_that_one(rf_repo):
    restate(rich(rf_repo), *NOISE)
    rf_repo.cli("rules", "baseline")
    base, _ = counts(rf_repo.cli("rules", "check")[1])
    restate(rf_repo, NOISE[0], "第2号文件由执行者加上并写进日记", NOISE[2])  # 改了中间一句
    _, out = rf_repo.cli("rules", "check")
    assert counts(out) == (base - 1, 1)  # 旧句子不在了，不算基线里的提醒；新句子重新报
    assert [ln for ln in listed(out) if RESTATE in ln] and "第2号文件由执行者加上并写进日记" in listed(out)[0]
    # 改回去，又在基线里了
    restate(rf_repo, *NOISE)
    assert counts(rf_repo.cli("rules", "check")[1]) == (base, 0)


def test_baseline_only_appends_and_is_stable(rf_repo):
    restate(rich(rf_repo), *NOISE)
    rf_repo.cli("rules", "baseline")
    first = (rf_repo.path / BASE).read_bytes()
    rf_repo.cli("rules", "baseline")  # 再记一次：没有新的，文件一字不动
    assert (rf_repo.path / BASE).read_bytes() == first
    restate(rf_repo, *NOISE, "第4号文件由执行者加上")
    rc, out = rf_repo.cli("rules", "baseline")
    now = (rf_repo.path / BASE).read_bytes()
    assert now.startswith(first) and len(now.split(b"\n")) == len(first.split(b"\n")) + 1  # 只在末尾多一行
    # 改掉一句再记：旧记录还在，新句子追加；out 里说明有几条已不在现有提醒里
    restate(rf_repo, NOISE[0], "第2号文件由执行者加上并写进日记", NOISE[2], "第4号文件由执行者加上")
    rc, out = rf_repo.cli("rules", "baseline")
    later = (rf_repo.path / BASE).read_bytes()
    assert later.startswith(now) and "其中 1 条已不在现有提醒里" in out


def test_baseline_records_have_file_hash_and_first_sixty_chars_with_lf_endings(rf_repo):
    long = "第9号文件由执行者加上" + "，再写进日记" * 20
    restate(rich(rf_repo), long)
    rf_repo.cli("rules", "baseline")
    raw = (rf_repo.path / BASE).read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    recs = [__import__("json").loads(x) for x in raw.decode("utf-8").split("\n") if x]
    mine = [r for r in recs if r["file"] == RESTATE]
    assert len(mine) == 1 and set(mine[0]) == {"file", "hash", "head"}
    assert mine[0]["head"] == long[:60] and re.fullmatch(r"[0-9a-f]{16}", mine[0]["hash"])


def test_same_input_gives_byte_identical_output_and_baseline(rf_repo):
    restate(rich(rf_repo), *NOISE)
    _, a = rf_repo.cli("rules", "baseline")
    f1 = (rf_repo.path / BASE).read_bytes()
    _, c1 = rf_repo.cli("rules", "check", "--all")
    _, c2 = rf_repo.cli("rules", "check", "--all")
    _, b = rf_repo.cli("rules", "baseline")
    assert c1 == c2 and (rf_repo.path / BASE).read_bytes() == f1 and "新增 0 条" in b


def test_hash_ignores_whitespace_and_list_markers_but_not_words():
    class H:  # 只用到 file、text、items
        def __init__(self, text, items=()):
            self.file, self.text, self.items = "a.md", text, list(items)

    assert baseline.key(H("第1号文件  由执行者加上")) == baseline.key(H("第1号文件 由执行者加上"))
    assert baseline.key(H("下面这些：", [(2, "- 甲")])) == baseline.key(H("下面这些：", [(2, "  * 甲")]))
    assert baseline.key(H("第1号文件由执行者加上")) != baseline.key(H("第1号文件由执行者写"))
    assert baseline.key(H("x")) != (("b.md",) + baseline.key(H("x"))[1:])
