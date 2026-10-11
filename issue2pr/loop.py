"""调度层：Agent 主循环。

只做调度：发消息、把工具结果回填、判断什么时候停。
不碰文件、不碰网络、不解析工具参数——那些分别在 model / tools 层。

几条设计决定来自参考实现：
  - 预算按模型调用次数算，超了就停，不产生任何费用（mini-swe-agent）
  - 结束与否由工具决定，不解析模型的话术（pi）
  - 消息只追加、不重写：轨迹可复盘，prompt cache 能命中（codex 的硬规矩）
"""

from __future__ import annotations

from typing import Callable

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

from .model import DEFAULT_MODEL, complete
from .prompt import SYSTEM_PROMPT
from .result import BUDGET_EXHAUSTED, FAILED, RunResult, TaskDone
from .tools import check_bindings, execute


class AgentLoop:
    """一次任务跑一遍：issue 丢进去，结论拿出来。"""

    def __init__(
        self,
        client: OpenAI,
        *,
        tools: list[ChatCompletionToolParam],
        handlers: dict[str, Callable[..., str]],
        model: str = DEFAULT_MODEL,
        max_steps: int = 20,
        max_consecutive_errors: int = 3,
        max_repeats: int = 3,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        check_bindings(tools, handlers)
        self.client = client
        self.tools = tools
        self.handlers = handlers
        self.model = model
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
            completion = complete(self.client, model=self.model, messages=messages, tools=self.tools)
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
                    output, failed = execute(
                        self.handlers, tool_call.function.name, tool_call.function.arguments
                    )
                except TaskDone as done:
                    return RunResult(done.status, done.reason, messages)
                errors += 1 if failed else 0
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": output})

            consecutive_errors = consecutive_errors + 1 if errors else 0
            if consecutive_errors >= self.max_consecutive_errors:
                return RunResult(FAILED, f"工具连续失败 {consecutive_errors} 轮", messages)

        return RunResult(BUDGET_EXHAUSTED, f"步数预算用完（{self.max_steps} 次模型调用）", messages)
