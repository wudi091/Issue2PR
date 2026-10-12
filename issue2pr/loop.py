"""调度层：Agent 主循环。

只做调度：发消息、把工具结果回填、判断什么时候停。
不碰文件、不碰网络、不解析工具参数——那些分别在 model / tools 层。

几条设计决定来自参考实现：
  - 预算按模型调用次数算，超了就停，不产生任何费用（mini-swe-agent）
  - 模型不再调用工具，就是它宣布干完了（dsh / codex）；工具抛 TaskDone 也能提前收工
  - 消息只追加、不重写：轨迹可复盘，prompt cache 能命中（codex 的硬规矩）
"""

from __future__ import annotations

from typing import Callable

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

from .model import DEFAULT_MODEL, complete
from .prompt import SYSTEM_PROMPT
from .result import BUDGET_EXHAUSTED, FAILED, RESOLVED, RunResult, TaskDone
from .tools import check_bindings, execute


def _budget_note(used: int, total: int) -> str:
    """把剩余预算写进观察结果。

    模型不知道自己在花什么，就会一直验证到预算耗尽——真跑里就是这么烧完 20 次的。
    mini-swe-agent 把同样的提醒放在观察结果模板里（`benchmarks/programbench.yaml`），
    只在剩余 < 20 时出现；我们预算小，每轮都给，并且说清用完的后果。
    """
    return (
        f"[预算] 已用 {used}/{total} 次模型调用，还剩 {total - used} 次；"
        "用完即停，届时仓库里的状态就是最终结果。"
    )


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
        for step in range(1, self.max_steps + 1):
            completion = complete(self.client, model=self.model, messages=messages, tools=self.tools)
            message = completion.choices[0].message
            # 返回的是 pydantic 对象，必须转成 dict 才能回填；exclude_none 避免 content: null
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                # 抄 dsh / codex：模型不再调用工具，就是它宣布这一轮干完了。
                # 唯一例外是被 max_tokens 截断——那不是它自己停的，推一把让它接着说。
                if completion.choices[0].finish_reason == "length" and not nudged:
                    nudged = True
                    messages.append(
                        {"role": "user", "content": "上一条回复被长度限制截断了，请接着说完。"}
                    )
                    continue
                return RunResult(
                    RESOLVED, (message.content or "").strip() or "模型不再调用工具", messages
                )
            nudged = False

            signature = tuple(f"{c.function.name}({c.function.arguments})" for c in message.tool_calls)
            repeats = repeats + 1 if signature == last_signature else 0
            last_signature = signature
            if repeats >= self.max_repeats:
                return RunResult(FAILED, "连续重复同一批工具调用，判定卡死", messages)

            errors = 0
            last = len(message.tool_calls) - 1
            for index, tool_call in enumerate(message.tool_calls):
                try:
                    output, failed = execute(
                        self.handlers, tool_call.function.name, tool_call.function.arguments
                    )
                except TaskDone as done:
                    return RunResult(done.status, done.reason, messages)
                errors += 1 if failed else 0
                if index == last:
                    # 预算挂在观察结果尾巴上，一轮只挂一次
                    output = f"{output}\n\n{_budget_note(step, self.max_steps)}"
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": output})

            consecutive_errors = consecutive_errors + 1 if errors else 0
            if consecutive_errors >= self.max_consecutive_errors:
                return RunResult(FAILED, f"工具连续失败 {consecutive_errors} 轮", messages)

        return RunResult(BUDGET_EXHAUSTED, f"步数预算用完（{self.max_steps} 次模型调用）", messages)
