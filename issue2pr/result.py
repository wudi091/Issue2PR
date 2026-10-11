"""契约层：任务结论的取值、结束信号、最终结果。

这三样 SDK 里没有对应物（SDK 只管一次请求/响应），所以只能自建。
除此之外，项目里不再自建任何类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openai.types.chat import ChatCompletionMessageParam

#: RunResult.status 的取值
RESOLVED = "resolved"
FAILED = "failed"
BUDGET_EXHAUSTED = "budget_exhausted"


class TaskDone(Exception):
    """工具用它喊停：任务有结论了。

    SDK 里没有「工具干完了」这种信号，用异常最省，也正好不用新建结果类型。
    """

    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        self.reason = reason
        super().__init__(f"{status}: {reason}")


@dataclass
class RunResult:
    """循环的最终结论。messages 直接复用 SDK 的消息类型，轨迹不再另建类型。"""

    status: str
    reason: str
    messages: list[ChatCompletionMessageParam] = field(default_factory=list)
