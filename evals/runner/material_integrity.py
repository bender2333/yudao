"""材料完整性与上游访问核对（评测场景设计第 3 节「联网」与「隔离」）。

两项核对都由运行器在评分之前调用：

* 摘要核对：把场景材料（隐藏检查、条目表、参考解法）逐个算成摘要，与材料
  版本记录（``materials/manifest.json`` 的 ``digests`` 块）比较。摘要不同说明
  评价标准被改动过，这次运行无效。
* 上游访问核对：在 OpenCode 的 JSON 输出与 Yudao 的事件日志导出里查找对任务
  上游仓库的访问。找到说明结果可能被上游答案污染，这次运行无效。

摘要的规范化形式是 LF 换行的字节流：仓库里的文件按 git 提交（LF），本机
签出可能带 CRLF（``core.autocrlf``），取 LF 以后摘要在不同平台上一致。跳过
``__pycache__`` 与 ``*.pyc``：测试或评分过程写下的字节码不是材料内容，不应
让摘要失效。
"""

import hashlib
import json
import os

ALGORITHM = "sha256"
NOTE = "LF 规范化、递归、跳过 __pycache__ 与 *.pyc"
MANIFEST_NAME = "manifest.json"
SKIPPED_DIRS = {"__pycache__"}


def digest_bytes(data):
    """一段字节流的摘要，格式与 harness/artifacts.py 一致。"""
    return ALGORITHM + ":" + hashlib.sha256(data).hexdigest()


def _digest_file(path):
    with open(path, "rb") as handle:
        return digest_bytes(handle.read().replace(b"\r\n", b"\n"))


def _walk(root):
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in SKIPPED_DIRS]
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            yield os.path.join(directory, name)


def entry_path(base, entry):
    """材料条目的路径与登记键：键用正斜杠，Windows 的反斜杠只在本机路径上出现。"""
    key = entry.replace("\\", "/")
    return os.path.join(base, *key.split("/")), key


def entry_digests(base, entry):
    """一个材料条目的摘要：文件算自身，目录递归其下全部文件后合并。

    目录的摘要是「相对路径 + 文件内容」按序拼接后再取摘要，因此改名、增删
    文件都会改变摘要，而不只是内容变化才会。
    """
    target, _key = entry_path(base, entry)
    if not os.path.exists(target):
        return None
    if os.path.isfile(target):
        return _digest_file(target)
    pieces = []
    for path in _walk(target):
        relative = os.path.relpath(path, target).replace("\\", "/")
        pieces.append(relative.encode("utf-8") + b"\0" + _digest_file(path).encode("ascii"))
    return digest_bytes(b"\n".join(pieces))


def record_digests(base):
    """材料版本记录里登记的摘要（没有记录时返回空字典）。"""
    manifest = os.path.join(base, "materials", MANIFEST_NAME)
    if not os.path.isfile(manifest):
        return {}
    with open(manifest, encoding="utf-8") as handle:
        digests = json.load(handle).get("digests") or {}
    return dict(digests.get("entries") or {})


def digest_reasons(base, entries):
    """摘要核对的原因列表：材料不存在、没有登记、摘要不同都写进原因。"""
    recorded = record_digests(base)
    reasons = []
    for entry in sorted(entries):
        actual = entry_digests(base, entry)
        expected = recorded.get(entry_path(base, entry)[1])
        if actual is None:
            reasons.append(f"材料条目不存在：{entry}")
        elif expected is None:
            reasons.append(f"材料条目没有登记摘要：{entry}")
        elif actual != expected:
            reasons.append(f"材料摘要与材料版本记录不同：{entry}")
    return reasons


def upstream_hits(text, urls):
    """在输出文本里查找对上游仓库的访问，返回命中的地址原样子串。

    同一地址按四种写法匹配：带协议、不带协议（git 的 scp 形式
    ``git@github.com:owner/repo.git`` 里没有 ``//``）、浏览器地址常省略协议，
    以及它们各自在 JSON 文本里的转义形式。与材料路径的匹配方式一致。
    """
    found = []
    for url in urls:
        bare = url.replace("https://", "").replace("http://", "").rstrip("/")
        forms = {url.rstrip("/"), bare, bare.replace("github.com/", "github.com:")}
        for candidate in sorted(forms | {json.dumps(form)[1:-1] for form in forms}):
            if candidate in text:
                found.append(candidate)
    return sorted(set(found))


def describe_urls(urls):
    return "、".join(sorted(set(urls)))


def write_digests(base, entries):
    """把摘要写回材料版本记录：材料改动以后重新生成，随改动一起提交。"""
    manifest = os.path.join(base, "materials", MANIFEST_NAME)
    with open(manifest, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["digests"] = {"algorithm": ALGORITHM, "note": NOTE,
                          "entries": {entry_path(base, entry)[1]: entry_digests(base, entry)
                                      for entry in sorted(entries)}}
    with open(manifest, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return payload["digests"]
