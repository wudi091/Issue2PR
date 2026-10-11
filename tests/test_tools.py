"""能力层的契约测试：参数怎么解析、失败怎么包装、什么时候该穿过去。

这一层不碰网络也不碰循环，全是纯函数，直接调就行。
"""

from __future__ import annotations

from typing import Any

import pytest

from issue2pr.result import RESOLVED, TaskDone
from issue2pr.tools import check_bindings, execute


def ghost_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "ghost",
            "description": "测试用工具",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    }


def test_bad_json_arguments_are_reported_as_a_failure() -> None:
    text, failed = execute({"echo": lambda **_: "ok"}, "echo", "{不是 json")

    assert failed is True
    assert "参数解析失败" in text


def test_arguments_that_are_not_an_object_are_rejected() -> None:
    text, failed = execute({"echo": lambda **_: "ok"}, "echo", '"字符串不是对象"')

    assert failed is True
    assert "必须是 JSON 对象" in text


def test_unknown_tool_is_reported_as_a_failure() -> None:
    text, failed = execute({}, "nope", "{}")

    assert failed is True
    assert "没有这个工具" in text


def test_tool_exception_becomes_an_observation_not_a_crash() -> None:
    def boom(**_: Any) -> str:
        raise RuntimeError("读不到文件")

    text, failed = execute({"boom": boom}, "boom", "{}")

    assert failed is True
    assert "RuntimeError" in text and "读不到文件" in text


def test_task_done_passes_through_instead_of_becoming_an_observation() -> None:
    def done(**_: Any) -> str:
        raise TaskDone(RESOLVED, "测试全绿")

    with pytest.raises(TaskDone):
        execute({"done": done}, "done", "{}")


def test_every_tool_schema_must_have_an_implementation() -> None:
    with pytest.raises(ValueError, match="只有 schema"):
        check_bindings([ghost_tool()], {})

    check_bindings([ghost_tool()], {"ghost": lambda **_: ""})  # 有实现就不该报
