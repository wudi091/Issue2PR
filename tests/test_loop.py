"""loop 的调度契约测试。

loop 是调度器，它的正确性就是「调度得对不对」：工具按什么顺序被调用、
预算有没有真的生效、卡死能不能识别、坏输入会不会把循环搞崩。
"""

from __future__ import annotations

import pytest

from issue2pr.loop import (
    BUDGET_EXHAUSTED,
    FAILED,
    RESOLVED,
    AgentLoop,
    Tool,
    ToolRegistry,
    ToolResult,
)


class FakeModel:
    """按剧本返回响应；剧本只剩一条时一直重复它（用来测预算和卡死）。"""

    def __init__(self, *script: dict) -> None:
        self.script = list(script)
        self.calls = 0

    def complete(self, messages: list[dict]) -> dict:
        self.calls += 1
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]


def call(name: str, args: str = "{}", call_id: str = "c1") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}],
    }


def registry(results: list[ToolResult], seen: list[dict] | None = None) -> ToolRegistry:
    """一个叫 echo 的工具：每次调用依次返回 results 里的结果。"""
    queue = list(results)

    def run(**kwargs: object) -> ToolResult:
        if seen is not None:
            seen.append(kwargs)
        return queue.pop(0) if queue else ToolResult("ok")

    tools = ToolRegistry()
    tools.register(
        Tool(
            name="echo",
            description="测试用工具",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
            run=run,
        )
    )
    return tools


def test_tools_run_in_order_and_tool_decides_the_end() -> None:
    seen: list[dict] = []
    tools = registry(
        [ToolResult("a"), ToolResult("b"), ToolResult("测试通过", terminate=True, status=RESOLVED)], seen
    )
    model = FakeModel(call("echo", '{"q": "1"}'), call("echo", '{"q": "2"}'), call("echo", '{"q": "3"}'))

    result = AgentLoop(model, tools).run("修个 bug")

    assert result.status == RESOLVED
    assert [s.args["q"] for s in result.steps] == ["1", "2", "3"]
    assert seen == [{"q": "1"}, {"q": "2"}, {"q": "3"}]
    assert [m["role"] for m in result.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]


def test_budget_is_checked_before_calling_the_model() -> None:
    model = FakeModel(call("echo"))
    result = AgentLoop(model, registry([ToolResult("ok")]), max_steps=3).run("修个 bug")

    assert result.status == BUDGET_EXHAUSTED
    assert len(result.steps) == 3
    assert model.calls == 3, "第 4 次应该在调模型之前就被拦住，不能产生费用"


def test_identical_batches_are_detected_as_stuck() -> None:
    result = AgentLoop(FakeModel(call("echo")), registry([ToolResult("ok")]), max_repeats=3).run("修个 bug")

    assert result.status == FAILED
    assert "重复" in result.reason
    assert len(result.steps) == 3


def test_consecutive_tool_errors_stop_the_loop() -> None:
    # 每次参数都不同，避免撞上「重复调用」那条判定，这样只测错误累计这一条
    model = FakeModel(call("echo", '{"q": "1"}'), call("echo", '{"q": "2"}'), call("echo", '{"q": "3"}'))
    tools = registry([ToolResult("读不到文件", error=True)] * 3)

    result = AgentLoop(model, tools, max_consecutive_errors=2).run("修个 bug")

    assert result.status == FAILED
    assert "连续失败 2 轮" in result.reason
    assert all(s.error for s in result.steps)


def test_bad_arguments_and_unknown_tools_are_reported_not_crashed() -> None:
    model = FakeModel(call("echo", "{不是 json"), call("没有这个工具"))
    result = AgentLoop(model, registry([])).run("修个 bug")

    assert [s.error for s in result.steps[:2]] == [True, True]
    assert "参数解析失败" in result.steps[0].result
    assert "没有这个工具" in result.steps[1].result


def test_model_talking_without_tools_gets_one_nudge_then_fails() -> None:
    talking = {"role": "assistant", "content": "我觉得应该改 calc.py"}
    result = AgentLoop(FakeModel(talking, talking), registry([])).run("修个 bug")

    assert result.status == FAILED
    assert "不调用工具" in result.reason
    assert sum(m.get("content") == "请用工具继续定位或修改，不要只描述。" for m in result.messages) == 1


def test_tool_schema_is_validated_and_registry_rejects_duplicates() -> None:
    with pytest.raises(ValueError):
        Tool(name="bad", description="x", parameters={"type": "array"}, run=lambda **_: ToolResult(""))

    tools = registry([])
    with pytest.raises(ValueError):
        tools.register(tools.get("echo"))
