"""环境层的契约测试：真实临时目录，不打桩。

重点验证两条规矩：
  1. 失败是返回值，不是异常（env 的方法一个都不许抛）
  2. 路径不许逃出工作目录
"""

from __future__ import annotations

from pathlib import Path

import pytest

from issue2pr.env import EnvError, err, ok
from issue2pr.local_env import LocalEnv

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
