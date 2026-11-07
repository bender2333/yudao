# 基线运行（docs/design/kernel-quality-gate.md「变异检查」）：在没有变异的副本里跑一遍内核测试，
# 同时用 coverage 记下覆盖、每个测试文件的耗时、每个文件执行到哪些模块。副本取自当前提交
# （git archive HEAD），不读工作区：检查的输入是提交，工作区里的改动不算。
#
# 每个测试文件单独一个进程运行，所以每个文件的耗时与覆盖分得开；合计覆盖是各文件覆盖的并集。
# 基线本身失败算工具出错：测试没通过、副本取不出来、单个文件超过上限没有跑完，都抛 BaselineError。
#
# 工具只读文件、起进程（git、pytest、coverage），不导入 harness/ 里的代码。

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import coverage
import psutil

# 内核目录的全部测试文件（docs/design/kernel-quality-gate.md「变异检查」）
KERNEL_TESTS = Path("harness/tests/kernel")

# 单个基线测试文件的上限：卡住的测试不能把工具拖到 CI 作业超时
FILE_TIMEOUT_SECONDS = 900

# 取当前提交的副本时，git 自己的上限
ARCHIVE_TIMEOUT_SECONDS = 600


class BaselineError(Exception):
    """基线本身失败：副本取不出来、测试没通过、一个文件跑超时。"""


@dataclass(frozen=True)
class TestFileRun:
    # 一个测试文件的基线：耗时（秒）与它执行到的内核模块（仓库内相对路径）
    test_file: str
    seconds: float
    covered_modules: tuple[str, ...]


@dataclass(frozen=True)
class Baseline:
    # 没有变异的副本与全部测试文件的运行结果。work_dir 由 cleanup 整个删掉。
    work_dir: Path
    tree: Path
    test_files: tuple[TestFileRun, ...]
    module_lines: dict[str, frozenset[int]]

    @property
    def seconds(self) -> float:
        return sum(item.seconds for item in self.test_files)

    def files_covering(self, module: str) -> tuple[TestFileRun, ...]:
        return tuple(item for item in self.test_files if module in item.covered_modules)

    def executed_lines(self, module: str) -> frozenset[int]:
        return self.module_lines.get(module, frozenset())


def kernel_test_files(root: Path) -> tuple[str, ...]:
    # 内核目录里按文件名排序的全部 test_*.py；没有测试文件时也算基线失败
    directory = root / KERNEL_TESTS
    if not directory.is_dir():
        raise BaselineError(f"找不到内核测试目录 {KERNEL_TESTS.as_posix()}（在 {root} 下）")
    files = tuple(sorted(path.relative_to(root).as_posix() for path in directory.glob("test_*.py")))
    if not files:
        raise BaselineError(f"内核测试目录 {KERNEL_TESTS.as_posix()} 里没有 test_*.py")
    return files


def run(root: Path) -> Baseline:
    # 取当前提交的副本，逐个测试文件运行并收覆盖。返回的副本由调用方 cleanup。
    work_dir = root / ".tmp" / f"kernel-checks-{uuid.uuid4().hex}"
    tree = work_dir / "baseline"
    try:
        work_dir.mkdir(parents=True)
        _extract_head(root, tree)
        test_files = kernel_test_files(root)
        runs: list[TestFileRun] = []
        merged: dict[str, set[int]] = {}
        for index, test_file in enumerate(test_files):
            data_file = work_dir / f"coverage-{index}.data"
            seconds, covered = _run_one(tree, test_file, data_file)
            for module, lines in covered.items():
                merged.setdefault(module, set()).update(lines)
            runs.append(
                TestFileRun(
                    test_file=test_file,
                    seconds=seconds,
                    covered_modules=tuple(sorted(covered)),
                )
            )
            data_file.unlink(missing_ok=True)
        return Baseline(
            work_dir=work_dir,
            tree=tree,
            test_files=tuple(runs),
            module_lines={module: frozenset(lines) for module, lines in merged.items()},
        )
    except BaseException:
        cleanup(work_dir)
        raise


def cleanup(work_dir: Path) -> None:
    shutil.rmtree(work_dir, ignore_errors=True)


def clone_tree(source: Path, destination: Path) -> None:
    # 每个并行任务一份自己的副本：变异写进这一份，别的任务看不到。尽量用硬链接，
    # 一个仓库的副本不用真的复制一遍；写变异的那一个文件先删掉再写，原副本不受影响。
    shutil.copytree(source, destination, symlinks=False, copy_function=_link_or_copy)


def _link_or_copy(source: str, destination: str) -> str:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def pytest_command(test_file: str) -> list[str]:
    # 变异判定只跑测试，不再收覆盖；基线用 coverage 包住同一条 pytest 命令
    return [sys.executable, "-m", "pytest", test_file, "-q", "-p", "no:cacheprovider"]


def coverage_command(test_file: str, data_file: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--source=harness",
        f"--data-file={data_file}",
        "-m",
        "pytest",
        test_file,
        "-q",
        "-p",
        "no:cacheprovider",
    ]


def environment(tree: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tree)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("COVERAGE_PROCESS_START", None)
    return env


def run_process(
    command: list[str], cwd: Path, env: dict[str, str], timeout: float | None
) -> subprocess.CompletedProcess[bytes]:
    # 起一个进程并等它结束；超时时结束整棵进程树（测试自己起的子进程也不能留下），再抛 TimeoutExpired
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        parent = psutil.Process(process.pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.Error:
        process.kill()


def _extract_head(root: Path, tree: Path) -> None:
    done = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
        timeout=ARCHIVE_TIMEOUT_SECONDS,
    )
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise BaselineError(f"取不出当前提交的副本：git archive HEAD 失败（{detail}）")
    tree.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(done.stdout), mode="r:") as archive:
        try:
            archive.extractall(tree, filter="data")
        except TypeError:  # Python 3.11.4 以前的 extractall 没有 filter 参数
            archive.extractall(tree)
    if not (tree / "pyproject.toml").exists() and not (tree / "pytest.ini").exists():
        # 副本没有 pytest 的配置文件时，自己的上级目录里的配置会被 pytest 找到（根目录会跑到仓库外）：
        # 放一个空的 pytest.ini 把根目录定在副本里
        (tree / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _run_one(tree: Path, test_file: str, data_file: Path) -> tuple[float, dict[str, tuple[int, ...]]]:
    command = coverage_command(test_file, data_file)
    started = time.monotonic()
    try:
        done = run_process(command, tree, environment(tree), FILE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise BaselineError(
            f"基线运行超时：{test_file} 超过 {FILE_TIMEOUT_SECONDS} 秒没有跑完"
        ) from exc
    seconds = time.monotonic() - started
    if done.returncode != 0:
        output = (done.stdout + done.stderr).decode("utf-8", "replace").strip().splitlines()
        tail = "\n".join(output[-20:])
        raise BaselineError(f"基线运行失败：{test_file} 退出码 {done.returncode}\n{tail}")
    return seconds, _covered_modules(tree, data_file)


def _covered_modules(tree: Path, data_file: Path) -> dict[str, tuple[int, ...]]:
    # 这个测试文件执行到的模块与行。coverage 把执行过的文件按绝对路径记下，换算成仓库内相对路径；
    # 只看副本里 harness/ 下的文件。
    if not data_file.exists():
        raise BaselineError(f"基线没有留下覆盖数据：{data_file.name}")
    data = coverage.CoverageData(basename=str(data_file))
    data.read()
    tree_root = tree.resolve()
    covered: dict[str, tuple[int, ...]] = {}
    for measured in data.measured_files():
        try:
            relative = Path(measured).resolve().relative_to(tree_root)
        except (OSError, ValueError):
            continue
        if relative.parts[:1] != ("harness",) or relative.suffix != ".py":
            continue
        if relative.parts[:2] == ("harness", "tests"):
            # 测试文件自己不算「执行到的模块」
            continue
        lines = data.lines(measured) or []
        if not lines:
            # --source 会把没有执行到的模块也放进 measured_files（行数为空）：这种不算执行到
            continue
        covered[relative.as_posix()] = tuple(sorted(lines))
    return covered
