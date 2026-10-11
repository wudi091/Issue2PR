"""环境层的契约测试：真实临时目录，不打桩。

重点验证两条规矩：
  1. 失败是返回值，不是异常（env 的方法一个都不许抛）
  2. 路径不许逃出工作目录
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from issue2pr.env import EnvError, err, ok
from issue2pr.env.local import LocalEnv

SOURCE = "def add(a, b):\n    return a + b\n"


def make_env(tmp_path: Path) -> LocalEnv:
    (tmp_path / "calc.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.txt").write_text("inner", encoding="utf-8")
    return LocalEnv(tmp_path)


def test_read_text_returns_the_contents(tmp_path: Path) -> None:
    result = make_env(tmp_path).read_text("calc.py")

    assert result.ok is True
    assert result.value == SOURCE


def test_missing_file_is_an_error_result_not_an_exception(tmp_path: Path) -> None:
    result = make_env(tmp_path).read_text("nope.py")

    assert result.ok is False
    assert "不是文件" in result.error


def test_directory_is_not_a_file(tmp_path: Path) -> None:
    result = make_env(tmp_path).read_text("sub")

    assert result.ok is False
    assert "不是文件" in result.error


def test_undecodable_file_is_an_error_result(tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
    result = LocalEnv(tmp_path).read_text("blob.bin")

    assert result.ok is False
    assert "读取失败" in result.error


def test_exists_reports_both_ways(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    assert env.exists("calc.py").value is True
    assert env.exists("nope.py").value is False


def test_list_dir_marks_directories_with_a_trailing_slash(tmp_path: Path) -> None:
    result = make_env(tmp_path).list_dir(".")

    assert result.ok is True
    assert result.value == ["calc.py", "sub/"]


def test_listing_a_file_is_an_error_result(tmp_path: Path) -> None:
    result = make_env(tmp_path).list_dir("calc.py")

    assert result.ok is False
    assert "不是目录" in result.error


def test_paths_escaping_the_workspace_are_rejected(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    assert env.absolute_path("../outside").ok is False
    assert env.read_text("../outside.txt").ok is False
    assert env.exists(str(tmp_path.parent / "elsewhere")).ok is False
    assert "越界" in env.absolute_path("../../etc/passwd").error


def test_absolute_path_does_not_require_the_path_to_exist(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    result = env.absolute_path("sub/not_created_yet.py")

    assert result.ok is True
    assert result.value == (tmp_path / "sub" / "not_created_yet.py").resolve()


def test_unwrap_raises_only_when_there_is_an_error() -> None:
    assert ok(7).unwrap() == 7

    with pytest.raises(EnvError, match="炸了"):
        err("炸了").unwrap()


def test_exec_runs_a_command_and_captures_stdout(tmp_path: Path) -> None:
    result = LocalEnv(tmp_path).exec([sys.executable, "-c", "print('hi')"])

    assert result.ok is True
    assert result.value.stdout.strip() == "hi"
    assert result.value.returncode == 0


def test_non_zero_exit_is_a_result_not_an_error(tmp_path: Path) -> None:
    """grep 没匹配就退 1——那是正常结果，不是失败。"""
    result = LocalEnv(tmp_path).exec([sys.executable, "-c", "import sys; sys.exit(3)"])

    assert result.ok is True
    assert result.value.returncode == 3


def test_a_string_command_runs_through_the_shell(tmp_path: Path) -> None:
    """走 shell 才有管道和重定向；这里用 echo 保证跨平台。"""
    result = LocalEnv(tmp_path).exec("echo hello")

    assert result.ok is True
    assert "hello" in result.value.stdout


def test_a_missing_command_is_an_error_result(tmp_path: Path) -> None:
    result = LocalEnv(tmp_path).exec(["definitely-not-a-real-binary-xyz"])

    assert result.ok is False
    assert "命令不存在" in result.error


def test_a_hanging_command_times_out_instead_of_blocking_forever(tmp_path: Path) -> None:
    result = LocalEnv(tmp_path).exec(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5
    )

    assert result.ok is False
    assert "超时" in result.error


def test_exec_defaults_to_the_workspace_and_rejects_an_outside_cwd(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    inside = env.exec([sys.executable, "-c", "import os; print(os.getcwd())"])
    assert Path(inside.value.stdout.strip()) == tmp_path

    assert env.exec([sys.executable, "-c", "print(1)"], cwd="..").ok is False
