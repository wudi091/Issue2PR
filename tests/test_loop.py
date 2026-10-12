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


def reply(
    *tool_calls: tuple[str, str], content: str | None = None, finish_reason: str | None = None
) -> ChatCompletion:
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
                {
                    "index": 0,
                    "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
                    "message": message,
                }
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


def test_model_stopping_without_tools_completes_the_loop() -> None:
    """dsh / codex 的规矩：模型不再调用工具，就是它宣布干完了。"""
    client = FakeClient(reply(content="我把 calc.py 的除零分支改掉了，测试全绿"))
    result = loop(client, {"echo": lambda **_: "ok"}).run("修个 bug")

    assert result.status == RESOLVED
    assert result.reason == "我把 calc.py 的除零分支改掉了，测试全绿"
    assert client.calls == 1, "模型停手就是收工，不该再多问一轮"


def test_stopping_without_saying_anything_still_carries_a_reason() -> None:
    client = FakeClient(reply(content=None))
    result = loop(client, {"echo": lambda **_: "ok"}).run("修个 bug")

    assert result.status == RESOLVED
    assert result.reason == "模型不再调用工具"


def test_a_truncated_reply_is_continued_instead_of_counted_as_done() -> None:
    """被 max_tokens 截断不是模型自己停的，不能当成收工。"""
    client = FakeClient(
        reply(content="结论是：", finish_reason="length"),
        reply(content="改完了，测试全绿"),
    )
    result = loop(client, {"echo": lambda **_: "ok"}).run("修个 bug")

    assert result.status == RESOLVED
    assert result.reason == "改完了，测试全绿"
    assert client.calls == 2


def test_truncation_only_gets_pushed_once() -> None:
    """一直被截断也不能无限推——推过一次就按它给的话收工。"""
    client = FakeClient(reply(content="结论是：", finish_reason="length"))
    result = loop(client, {"echo": lambda **_: "ok"}).run("修个 bug")

    assert result.status == RESOLVED
    assert result.reason == "结论是："
    assert client.calls == 2


def test_assistant_message_is_dumped_without_none_fields() -> None:
    client = FakeClient(reply(("echo", '{"q": "1"}')))
    result = loop(client, {"echo": lambda **_: "ok"}, max_steps=1).run("修个 bug")

    assistant = next(m for m in result.messages if m["role"] == "assistant")
    assert "content" not in assistant, "exclude_none 没生效的话 content: null 可能被 DeepSeek 拒"
    assert assistant["tool_calls"][0]["function"]["name"] == "echo"


def test_every_observation_carries_the_remaining_budget() -> None:
    """模型得知道自己在花什么，才知道什么时候该收手。"""
    client = FakeClient(reply(("echo", '{"q": "1"}')), reply(content="改完了"))
    result = loop(client, {"echo": lambda **_: "ok"}, max_steps=5).run("修个 bug")

    tool_messages = [m["content"] for m in result.messages if m["role"] == "tool"]
    assert "[预算] 已用 1/5 次模型调用，还剩 4 次" in tool_messages[0]
    assert "ok" in tool_messages[0], "预算只是附加，命令输出本身不能被吃掉"


def test_budget_note_is_attached_once_per_turn() -> None:
    """一轮里调了多个工具，只在最后一条观察结果上挂一次。"""
    client = FakeClient(
        reply(("echo", '{"q": "1"}'), ("echo", '{"q": "2"}')), reply(content="改完了")
    )
    result = loop(client, {"echo": lambda **_: "ok"}, max_steps=5).run("修个 bug")

    tool_messages = [m["content"] for m in result.messages if m["role"] == "tool"]
    assert len(tool_messages) == 2
    assert "[预算]" not in tool_messages[0]
    assert "[预算]" in tool_messages[1]
