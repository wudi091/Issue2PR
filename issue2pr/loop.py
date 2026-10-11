"""Agent 主循环。

这一层只管调度：把消息发给模型、执行它要的工具、把结果回填、判断什么时候停。
不碰文件、不碰网络细节、不知道工具内部怎么实现。

线格式一律用 openai SDK 的类型，不自建：
  - 消息      → ChatCompletionMessageParam
  - 工具 schema → ChatCompletionToolParam
  - 工具调用   → SDK 返回的 message.tool_calls
  - 工具实现   → dict[str, Callable]，返回 str（观察结果）

自建的只剩两个，都是 SDK 覆盖不到的领域概念：
  - TaskDone：工具用它喊停（SDK 里没有"工具干完了"这种信号）
  - RunResult：循环的最终结论

几条设计决定来自参考实现：
  - 预算按**模型调用次数**算，超了就停，不产生任何费用（mini-swe-agent）
  - 结束与否由**工具**决定，不解析模型的话术（pi）
  - 消息只追加、不重写：轨迹可复盘，prompt cache 能命中（codex 的硬规矩）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

log = logging.getLogger("issue2pr")

#: RunResult.status 的取值
RESOLVED = "resolved"
FAILED = "failed"
BUDGET_EXHAUSTED = "budget_exhausted"

SYSTEM_PROMPT = """你是一个仓库级 issue 修复 Agent。

工作方式：
1. 先定位，再修改。没看清相关代码之前不要动手编辑。
2. 修改要最小化，只改与 issue 直接相关的代码，不顺手重构、不调整格式。
3. 每次修改后跑测试验证。测试失败时把失败信息当线索，而不是当要绕过的障碍。
4. 不要臆造文件内容或测试结果，不要通过修改测试来让测试通过。
5. 多次尝试仍不通过，就如实说明卡在哪里。"""


class TaskDone(Exception):
    """工具用它喊停：任务有结论了。

    SDK 里没有对应信号，用异常最省，也正好不用新建结果类型。
    """

    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        self.reason = reason
        super().__init__(f"{status}: {reason}")


@dataclass
class RunResult:
    status: str
    reason: str
    messages: list[ChatCompletionMessageParam] = field(default_factory=list)


class AgentLoop:
    def __init__(
        self,
        client: OpenAI,
        *,
        model: str,
        tools: list[ChatCompletionToolParam],
        handlers: dict[str, Callable[..., str]],
        max_steps: int = 20,
        max_consecutive_errors: int = 3,
        max_repeats: int = 3,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        unbound = [tool["function"]["name"] for tool in tools if tool["function"]["name"] not in handlers]
        if unbound:
            raise ValueError(f"这些工具只有 schema、没有实现：{unbound}")

        self.client = client
        self.model = model
        self.tools = tools
        self.handlers = handlers
        self.max_steps = max_steps
        self.max_consecutive_errors = max_consecutive_errors
        self.max_repeats = max_repeats
        self.system_prompt = system_prompt

    def run(self, issue: str) -> RunResult:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": issue.strip()},
        ]
        consecutive_errors = 0
        repeats = 0
        last_signature: tuple[str, ...] | None = None
        nudged = False

        # max_steps 是「最多几次模型调用」——每次调用都花钱，所以按调用次数算
        for _ in range(self.max_steps):
            completion = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=self.tools
            )
            message = completion.choices[0].message
            # 返回的是 pydantic 对象，必须转成 dict 才能回填；exclude_none 避免 content: null
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                # 模型只说话不动手。给一次纠正机会，再犯就当失败收工
                if nudged:
                    return RunResult(FAILED, "模型连续两轮不调用工具", messages)
                nudged = True
                messages.append({"role": "user", "content": "请用工具继续定位或修改，不要只描述。"})
                continue
            nudged = False

            signature = tuple(f"{c.function.name}({c.function.arguments})" for c in message.tool_calls)
            repeats = repeats + 1 if signature == last_signature else 0
            last_signature = signature
            if repeats >= self.max_repeats:
                return RunResult(FAILED, "连续重复同一批工具调用，判定卡死", messages)

            errors = 0
            for tool_call in message.tool_calls:
                try:
                    output, failed = self._execute(tool_call.function.name, tool_call.function.arguments)
                except TaskDone as done:
                    return RunResult(done.status, done.reason, messages)
                errors += 1 if failed else 0
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": output})

            consecutive_errors = consecutive_errors + 1 if errors else 0
            if consecutive_errors >= self.max_consecutive_errors:
                return RunResult(FAILED, f"工具连续失败 {consecutive_errors} 轮", messages)

        return RunResult(BUDGET_EXHAUSTED, f"步数预算用完（{self.max_steps} 次模型调用）", messages)

    def _execute(self, name: str, arguments: str) -> tuple[str, bool]:
        """执行一次工具调用，返回 (观察结果, 是否失败)。

        工具自己的失败不往外抛：转成观察结果回填，让模型有机会自我修正。
        """
        try:
            args: Any = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("参数必须是 JSON 对象")
        except (json.JSONDecodeError, ValueError) as exc:
            return f"参数解析失败：{exc}", True

        handler = self.handlers.get(name)
        if handler is None:
            return f"没有这个工具：{name}", True

        try:
            return handler(**args), False
        except TaskDone:
            raise
        except Exception as exc:  # noqa: BLE001 —— 工具的任何失败都回填给模型，别让循环崩掉
            log.exception("工具 %s 执行失败", name)
            return f"工具执行失败：{type(exc).__name__}: {exc}", True
