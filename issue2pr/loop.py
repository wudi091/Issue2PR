"""Agent 主循环。

这一层只管调度：把消息发给模型、执行它要的工具、把结果回填、判断什么时候停。
不碰文件、不碰网络、不知道工具内部怎么实现——这是三层里「调度层」的全部职责。

几条设计决定来自参考实现：
  - 预算在调模型**之前**检查（mini-swe-agent）：超了就停，不产生任何费用
  - 结束与否由**工具**决定，不解析模型的话术（pi）：工具返回 terminate 才算完
  - 消息只追加、不重写：轨迹可复盘，prompt cache 能命中（codex 的硬规矩）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

#: 消息就用 OpenAI 的线格式，不另造一层再转换
Message = dict[str, Any]

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


@dataclass
class ToolResult:
    """一次工具调用的结果。

    terminate 交给工具自己判断：只有工具知道任务是不是真结束了。
    靠解析模型的"我改好了"来决定收工，是不可靠的。
    """

    text: str
    terminate: bool = False
    status: str | None = None
    error: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., ToolResult]

    def __post_init__(self) -> None:
        if self.parameters.get("type") != "object" or not self.parameters.get("properties"):
            raise ValueError(f"工具 {self.name} 的 parameters 必须是带 properties 的 object schema")

    def call(self, **kwargs: Any) -> ToolResult:
        return self.run(**kwargs)

    def schema(self) -> dict[str, Any]:
        """转成 OpenAI tools 格式；换供应商只改这一处。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """工具注册表：循环只通过它拿工具，不直接 import 具体实现。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"工具重名：{tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]


class Model(Protocol):
    """模型接口。真实实现和测试用的假实现都只要满足这一个方法。"""

    def complete(self, messages: list[Message]) -> Message: ...


@dataclass
class Step:
    """一次工具调用及其观察结果。"""

    index: int
    tool: str
    args: dict[str, Any]
    result: str
    error: bool = False


@dataclass
class RunResult:
    status: str
    reason: str
    steps: list[Step] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)


class AgentLoop:
    def __init__(
        self,
        model: Model,
        tools: ToolRegistry,
        *,
        max_steps: int = 20,
        max_consecutive_errors: int = 3,
        max_repeats: int = 3,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.model = model
        self.tools = tools
        self.max_steps = max_steps
        self.max_consecutive_errors = max_consecutive_errors
        self.max_repeats = max_repeats
        self.system_prompt = system_prompt
        self.messages: list[Message] = []
        self.steps: list[Step] = []

    def run(self, issue: str) -> RunResult:
        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": issue.strip()},
        ]
        self.steps = []
        consecutive_errors = 0
        repeats = 0
        last_signature: tuple[str, ...] | None = None
        nudged = False

        while True:
            # 预算在调模型之前检查：超了就停，不产生任何费用
            if len(self.steps) >= self.max_steps:
                return self._result(BUDGET_EXHAUSTED, f"步数预算用完（{self.max_steps} 步）")

            message = self.model.complete(self.messages)
            self.messages.append(message)
            calls = message.get("tool_calls") or []

            if not calls:
                # 模型只说话不动手。给一次纠正机会，再犯就当失败收工
                if nudged:
                    return self._result(FAILED, "模型连续两轮不调用工具")
                nudged = True
                self.messages.append({"role": "user", "content": "请用工具继续定位或修改，不要只描述。"})
                continue
            nudged = False

            signature = tuple(
                f"{call['function']['name']}({call['function'].get('arguments', '')})" for call in calls
            )
            repeats = repeats + 1 if signature == last_signature else 0
            last_signature = signature
            if repeats >= self.max_repeats:
                return self._result(FAILED, "连续重复同一批工具调用，判定卡死")

            results = [self._execute(call) for call in calls]
            consecutive_errors = consecutive_errors + 1 if any(r.error for r in results) else 0
            if consecutive_errors >= self.max_consecutive_errors:
                return self._result(FAILED, f"工具连续失败 {consecutive_errors} 轮")

            # 工具说结束才算结束；status 由工具给，没给就按失败算
            if all(r.terminate for r in results):
                status = next((r.status for r in reversed(results) if r.status), FAILED)
                return self._result(status, "工具判定任务结束")

    def _execute(self, call: Message) -> ToolResult:
        """执行一次工具调用，把观察结果回填进 messages，并记录成 Step。"""
        name = call["function"]["name"]
        args: dict[str, Any] = {}
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("参数必须是 JSON 对象")
        except (json.JSONDecodeError, ValueError) as exc:
            result = ToolResult(text=f"参数解析失败：{exc}", error=True)
        else:
            try:
                result = self.tools.get(name).call(**args)
            except KeyError:
                result = ToolResult(text=f"没有这个工具：{name}", error=True)

        self.steps.append(
            Step(index=len(self.steps), tool=name, args=args, result=result.text, error=result.error)
        )
        self.messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result.text})
        return result

    def _result(self, status: str, reason: str) -> RunResult:
        return RunResult(status=status, reason=reason, steps=list(self.steps), messages=list(self.messages))
