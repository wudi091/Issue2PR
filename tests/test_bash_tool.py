"""bash 工具的契约测试：真实子进程，真跑命令。

重点验证一条：**命令的任何结果都是观察结果，不是工具失败**。
"""

from __future__ import annotations

import sys
from pathlib import Path

from issue2pr.bash_tool import BASH_SCHEMA, DEFAULT_TIMEOUT, MAX_LINES, make_bash_handler
from issue2pr.local_env import LocalEnv
from issue2pr.tools import check_bindings, execute


def py(code: str) -> str:
    """用当前解释器跑一段代码——跨平台，且不用管两种 shell 的引号规则。"""
    return f'"{sys.executable}" -c "{code}"'


def handler(tmp_path: Path):
    return make_bash_handler(LocalEnv(tmp_path))


def test_runs_a_command_and_returns_its_output(tmp_path: Path) -> None:
    assert "hello" in handler(tmp_path)("echo hello")


def test_commands_run_inside_the_workspace(tmp_path: Path) -> None:
    handler(tmp_path)("echo hi > made.txt")

    assert (tmp_path / "made.txt").exists()


def test_nonzero_exit_is_reported_in_the_observation(tmp_path: Path) -> None:
    assert "[exit code: 3]" in handler(tmp_path)("exit 3")


def test_a_failing_command_is_not_a_tool_failure(tmp_path: Path) -> None:
    """grep 没匹配退 1、测试跑挂退 1——都是模型该读到的信息，不是工具坏了。"""
    handlers = {"bash": handler(tmp_path)}

    output, failed = execute(handlers, "bash", '{"command": "exit 1"}')

    assert failed is False
    assert "[exit code: 1]" in output


def test_stderr_is_included_and_marked(tmp_path: Path) -> None:
    output = handler(tmp_path)("echo oops 1>&2")

    assert "[stderr]" in output
    assert "oops" in output


def test_success_without_output_says_so(tmp_path: Path) -> None:
    assert handler(tmp_path)(py("pass")) == "(命令执行成功，无输出)"


def test_long_output_keeps_the_tail(tmp_path: Path) -> None:
    last = MAX_LINES + 499
    output = handler(tmp_path)(py(f"print(chr(10).join(str(i) for i in range({last + 1})))"))

    assert output.startswith("[输出过长")
    assert str(last) in output, "最后一行必须留着"
    assert "\n0\n" not in output, "开头应该被砍掉"


def test_timeout_is_an_observation_not_an_exception(tmp_path: Path) -> None:
    output = handler(tmp_path)(py("import time; time.sleep(30)"), timeout=0.5)

    assert "命令没能执行" in output
    assert "超时" in output


def test_schema_binds_to_the_handler(tmp_path: Path) -> None:
    check_bindings([BASH_SCHEMA], {"bash": handler(tmp_path)})

    assert BASH_SCHEMA["function"]["name"] == "bash"
    assert BASH_SCHEMA["function"]["parameters"]["required"] == ["command"]
    assert DEFAULT_TIMEOUT > 0
