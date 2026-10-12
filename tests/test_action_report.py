"""report 层的契约测试：轨迹怎么变成人看的说明。

这一层是**纯格式化**，所以能测得很死——不碰 git、不碰网络。
"""

from __future__ import annotations

from issue2pr.action.report import Step, failure_comment, pr_body, steps_from


def assistant(*calls: tuple[str, str, str]) -> dict:
    """(call_id, name, arguments) → 一条 assistant 消息。"""
    return {
        "role": "assistant",
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}
            for call_id, name, args in calls
        ],
    }


def tool(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_steps_pair_commands_with_their_outputs() -> None:
    messages = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "修个 bug"},
        assistant(("c1", "bash", '{"command": "dir /b"}')),
        tool("c1", "calc.py\ntests"),
    ]

    assert steps_from(messages) == [Step(command="bash dir /b", output="calc.py\ntests")]


def test_several_calls_in_one_reply_keep_their_order() -> None:
    """结果靠 tool_call_id 回配，顺序不能猜。"""
    messages = [
        assistant(("c1", "bash", '{"command": "a"}'), ("c2", "bash", '{"command": "b"}')),
        tool("c1", "第一个"),
        tool("c2", "第二个"),
    ]

    steps = steps_from(messages)

    assert [s.command for s in steps] == ["bash a", "bash b"]
    assert [s.output for s in steps] == ["第一个", "第二个"]


def test_long_outputs_are_clipped() -> None:
    messages = [assistant(("c1", "bash", '{"command": "x"}')), tool("c1", "y" * 1000)]

    step = steps_from(messages, output_chars=10)[0]

    assert step.output.startswith("y" * 10)
    assert "共 1000 字符" in step.output


def test_a_run_that_never_called_a_tool_has_no_steps() -> None:
    assert steps_from([{"role": "assistant", "content": "我修好了"}]) == []


def test_broken_arguments_do_not_crash_the_report() -> None:
    messages = [assistant(("c1", "bash", "不是 JSON")), tool("c1", "ok")]

    assert steps_from(messages)[0].command == "bash 不是 JSON"


def test_pr_body_carries_the_summary_the_commands_and_the_warning() -> None:
    body = pr_body(
        issue_number=7,
        summary="把 median 改成偶数取平均，15 passed。",
        steps=[Step(command="bash python -m pytest -q", output="15 passed in 0.02s")],
        model="deepseek-flash",
    )

    assert "修复 #7" in body
    assert "把 median 改成偶数取平均，15 passed。" in body
    assert "python -m pytest -q" in body
    assert "15 passed in 0.02s" in body
    assert "没有独立验证" in body, "这句必须留着：成没成最终要人判断"


def test_failure_comment_says_no_pull_request_was_opened() -> None:
    body = failure_comment(issue_number=7, summary="卡在依赖装不上。", steps=[], model="m")

    assert "没有开 PR" in body
    assert "卡在依赖装不上。" in body
    assert "它没有跑过任何命令" in body


def test_an_empty_summary_still_produces_valid_markdown() -> None:
    body = pr_body(issue_number=1, summary="   ", steps=[], model="m")

    assert "它没有留下说明" in body
