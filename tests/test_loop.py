"""调度层的契约测试：loop 的正确性就是「调度得对不对」。

假 client 返回的是**真的 ChatCompletion 对象**（SDK 类型构造），
所以测试与真实响应同构，但不联网、不花 API key。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from openai.types.chat import ChatCompletion

from issue2pr.loop import AgentLoop
from issue2pr.result import BUDGET_EXHAUSTED, FAILED, RESOLVED, TaskDone


def reply(*tool_calls: tuple[str, str], content: str | None = None) -> ChatCompletion:
    """造一个真的 ChatCompletion 响应。"""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": args}}
            for i, (name, args) in enumerate(tool_calls)
        ]
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop", "message": message}
            ],
        }
    )


class FakeClient:
    """假 client：按剧本返回响应；剧本只剩一条时一直重复它（用来测预算和卡死）。"""

    def __init__(self, *script: ChatCompletion) -> None:
        self.script = list(script)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> ChatCompletion:
        self.calls += 1
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]


def loop(client: FakeClient, handlers: dict[str, Any], **kwargs: Any) -> AgentLoop:
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"测试用工具 {name}",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        }
        for name in handlers
    ]
    return AgentLoop(client, model="test", tools=tools, handlers=handlers, **kwargs)


def test_tools_run_in_order_and_task_done_stops_the_loop() -> None:
    seen: list[dict[str, Any]] = []

    def echo(**kwargs: Any) -> str:
        seen.append(kwargs)
        if kwargs["q"] == "3":
            raise TaskDone(RESOLVED, "测试全绿")
        return "ok"

    client = FakeClient(
        reply(("echo", '{"q": "1"}')), reply(("echo", '{"q": "2"}')), reply(("echo", '{"q": "3"}'))
    )
    result = loop(client, {"echo": echo}).run("修个 bug")

    assert result.status == RESOLVED
    assert result.reason == "测试全绿"
    assert seen == [{"q": "1"}, {"q": "2"}, {"q": "3"}]
    # 观察结果以 tool 角色回填；抛 TaskDone 那次不产生观察结果，直接收工
    assert [m["role"] for m in result.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]


def test_budget_counts_model_calls() -> None:
    client = FakeClient(reply(("echo", '{"q": "1"}')))
    result = loop(client, {"echo": lambda **_: "ok"}, max_steps=3).run("修个 bug")

    assert result.status == BUDGET_EXHAUSTED
    assert client.calls == 3, "预算按模型调用次数算，超一次都不行"


def test_identical_batches_are_detected_as_stuck() -> None:
    seen: list[dict[str, Any]] = []

    def echo(**kwargs: Any) -> str:
        seen.append(kwargs)
        return "ok"

    client = FakeClient(reply(("echo", '{"q": "1"}')))
    result = loop(client, {"echo": echo}).run("修个 bug")

    assert result.status == FAILED
    assert "重复" in result.reason
    assert len(seen) == 3, "第 4 轮应该在动手之前就被拦住"
    assert client.calls == 4


def test_consecutive_tool_failures_stop_the_loop() -> None:
    def boom(**kwargs: Any) -> str:
        raise RuntimeError("读不到文件")

    client = FakeClient(
        reply(("echo", '{"q": "1"}')), reply(("echo", '{"q": "2"}')), reply(("echo", '{"q": "3"}'))
    )
    result = loop(client, {"echo": boom}, max_consecutive_errors=2).run("修个 bug")

    assert result.status == FAILED
    assert "连续失败 2 轮" in result.reason


def test_model_talking_without_tools_gets_one_nudge_then_fails() -> None:
    client = FakeClient(reply(content="我觉得应该改 calc.py"))
    result = loop(client, {"echo": lambda **_: "ok"}).run("修个 bug")

    assert result.status == FAILED
    assert "不调用工具" in result.reason
    assert sum(m.get("content") == "请用工具继续定位或修改，不要只描述。" for m in result.messages) == 1


def test_assistant_message_is_dumped_without_none_fields() -> None:
    client = FakeClient(reply(("echo", '{"q": "1"}')))
    result = loop(client, {"echo": lambda **_: "ok"}, max_steps=1).run("修个 bug")

    assistant = next(m for m in result.messages if m["role"] == "assistant")
    assert "content" not in assistant, "exclude_none 没生效的话 content: null 可能被 DeepSeek 拒"
    assert assistant["tool_calls"][0]["function"]["name"] == "echo"
