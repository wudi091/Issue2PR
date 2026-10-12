"""测试夹具。

**为什么覆盖 pytest 内置的 `tmp_path`**：本机环境下，pytest 在系统临时目录
（`%TEMP%\\pytest-of-<user>`）里创建的目录会在创建后变成不可读，
之后每次运行都在 setup 阶段报 `PermissionError: [WinError 5]`。

这里用同名夹具覆盖内置版本：对测试代码语义完全一致，
但临时目录落在仓库内 `tests/.tmp/` 下，用完即删，不依赖系统临时目录。

另外两个夹具给「要真跑 git」的测试用——git 层和 publish 层都建在真仓库上，
不 mock。
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from issue2pr.env import Env
from issue2pr.env.local import LocalEnv

TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """覆盖 pytest 内置夹具：语义一致，位置改到仓库内。"""
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TMP_ROOT / uuid.uuid4().hex[:12]
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def run_git() -> Callable[..., str]:
    """跑一条 git 命令；失败就直接炸——测试里不该有静默的 git 错误。"""

    def run(env: Env, *args: str) -> str:
        result = env.exec(["git", *args])
        assert result.ok, result.error
        assert result.value.returncode == 0, result.value.stderr
        return result.value.stdout or ""

    return run


@pytest.fixture
def git_repo(tmp_path: Path, run_git: Callable[..., str]) -> LocalEnv:
    """一个已经有一次提交的真仓库。

    建在 `tmp_path/work` 下，这样裸仓库（假远端）可以放旁边，
    既不污染工作区，也不会被 `git add -A` 顺手加进去。
    """
    work = tmp_path / "work"
    work.mkdir()
    env = LocalEnv(work)
    run_git(env, "init", "-b", "main")
    run_git(env, "config", "user.name", "测试")
    run_git(env, "config", "user.email", "test@example.com")
    (work / "calc.py").write_text("x = 1\n", encoding="utf-8")
    run_git(env, "add", "-A")
    run_git(env, "commit", "-m", "init")
    return env
