"""把一次运行写成人看的说明。

PR 描述和 issue 评论都从这里出。两份都**带证据**——Agent 敲过的命令、它看到的输出。
这不是装饰：我们只信模型自己说「测试全绿」，**没有独立验证**，
所以判断成没成最终要靠人看轨迹。这句话也写在正文里，不藏着。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

OUTPUT_CHARS = 400
PROJECT = "https://github.com/wudi091/Issue2PR"


@dataclass(frozen=True)
class Step:
    """Agent 敲的一条命令，以及它看到的输出。"""

    command: str
    output: str


def _describe(call: dict) -> str:
    """把一次工具调用写成人看的一行。

    只有一个工具时本可以更简单，但把 bash 的 command 摊开比
    `bash {"command": "dir /b"}` 好读太多，这个特例值得留。
    """
    function = call.get("function") or {}
    name = function.get("name", "?")
    raw = function.get("arguments", "")
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return f"{name} {raw}"
    if isinstance(parsed, dict) and "command" in parsed:
        return f"{name} {parsed['command']}"
    return f"{name} {raw}"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…（共 {len(text)} 字符）"


def steps_from(messages: Sequence[dict], *, output_chars: int = OUTPUT_CHARS) -> list[Step]:
    """按顺序把轨迹压成「命令 + 输出」。

    工具结果靠 `tool_call_id` 回配——一次回复里可能有多个调用，顺序不能猜。
    """
    outputs = {
        message.get("tool_call_id"): message.get("content", "")
        for message in messages
        if message.get("role") == "tool"
    }
    steps: list[Step] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            steps.append(
                Step(
                    command=_describe(call),
                    output=_clip(outputs.get(call.get("id"), ""), output_chars),
                )
            )
    return steps


def _evidence(steps: Sequence[Step]) -> str:
    if not steps:
        return "_它没有跑过任何命令。_"
    blocks = []
    for index, step in enumerate(steps, 1):
        block = [f"**{index}. `{step.command}`**"]
        if step.output.strip():
            block += ["", "```", step.output.rstrip(), "```"]
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def _footer(model: str) -> str:
    return (
        f"> 由 [Issue2PR]({PROJECT}) 自动生成，模型 `{model}`。\n"
        "> **请人工 review**：它只保证「Agent 自己认为测试通过了」，**没有独立验证**。"
    )


def pr_body(*, issue_number: int, summary: str, steps: Sequence[Step], model: str) -> str:
    """成功时的 PR 描述。"""
    return "\n".join(
        [
            f"修复 #{issue_number}。",
            "",
            "### Agent 的说明",
            "",
            summary.strip() or "_（它没有留下说明）_",
            "",
            "### 它跑过的命令",
            "",
            _evidence(steps),
            "",
            "---",
            "",
            _footer(model),
        ]
    )


def failure_comment(*, issue_number: int, summary: str, steps: Sequence[Step], model: str) -> str:
    """失败时的 issue 评论。"""
    return "\n".join(
        [
            f"没能修好 #{issue_number}，**没有开 PR**。",
            "",
            "### 卡在哪",
            "",
            summary.strip() or "_（它没有留下说明）_",
            "",
            "### 它试过什么",
            "",
            _evidence(steps),
            "",
            "---",
            "",
            _footer(model),
        ]
    )
