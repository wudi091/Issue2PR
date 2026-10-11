"""bash 工具：模型唯一的能力入口。

搜索、读文件、跑测试全走它。跟 mini-swe-agent 一样只给一个工具——
所以「怎么定位代码」由模型自己决定，这正好就是文本搜索定位的基线。

输出对齐 pi：
  - stdout 与 stderr 合并返回
  - 超长时**保留尾部**（命令的报错通常在最后），2000 行或 50KB 先到先算

一条刻意的偏离：**任何命令结果都不算工具失败**。
grep 没匹配退 1、测试跑挂退 1，都是模型该读到的信息，不是工具坏了。
退出码写在观察结果里（`[exit code: N]`），让模型自己判断。
`failed` 只留给工具实现真的崩了的情况——否则循环里那个
「连续失败 3 轮就停」的保险会在模型正常迭代测试时误杀。
"""

from __future__ import annotations

from typing import Callable

from openai.types.chat import ChatCompletionToolParam

from ..env import Env

MAX_LINES = 2000
MAX_BYTES = 50 * 1024
DEFAULT_TIMEOUT = 120.0
MAX_TIMEOUT = 3600.0

BASH_SCHEMA: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "在工作目录里执行一条 bash 命令，返回 stdout 与 stderr 合并后的输出。"
            f"输出超过 {MAX_LINES} 行或 {MAX_BYTES // 1024}KB 时只保留最后一部分（先到先算）。"
            "非 0 退出码会写在输出末尾。可选传 timeout（秒）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 bash 命令"},
                "timeout": {
                    "type": "number",
                    "description": f"超时秒数，默认 {DEFAULT_TIMEOUT:g}，上限 {MAX_TIMEOUT:g}",
                },
            },
            "required": ["command"],
        },
    },
}


def _truncate_tail(text: str) -> tuple[str, bool]:
    """保留尾部。先按行砍，再按字节砍，两级都可能触发。"""
    lines = text.splitlines()
    truncated = len(lines) > MAX_LINES
    if truncated:
        lines = lines[-MAX_LINES:]
    text = "\n".join(lines)

    encoded = text.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        # 从字节边界切尾部，errors="ignore" 吃掉可能被切一半的首字符
        text = encoded[-MAX_BYTES:].decode("utf-8", errors="ignore")
        truncated = True
    return text, truncated


def make_bash_handler(env: Env) -> Callable[..., str]:
    """造一个绑定到某个环境的 bash 实现。

    env 用闭包注入——模型给的参数会直接展开成关键字参数，
    env 混在里面会被参数污染。
    """

    def bash(command: str, timeout: float = DEFAULT_TIMEOUT) -> str:
        timeout = max(1.0, min(float(timeout), MAX_TIMEOUT))
        result = env.exec(command, timeout=timeout)
        if not result.ok:
            # 超时、找不到命令、cwd 越界——同样是观察结果，交给模型处理
            return f"[命令没能执行] {result.error}"

        completed = result.value
        text = (completed.stdout or "").rstrip()
        if completed.stderr and completed.stderr.strip():
            stderr = completed.stderr.rstrip()
            text = f"{text}\n[stderr]\n{stderr}" if text else f"[stderr]\n{stderr}"

        text, truncated = _truncate_tail(text)
        if truncated:
            text = f"[输出过长，只保留最后 {MAX_LINES} 行 / {MAX_BYTES // 1024}KB]\n{text}"

        if completed.returncode != 0:
            text = f"{text}\n[exit code: {completed.returncode}]" if text else f"[exit code: {completed.returncode}]"
        elif not text:
            text = "(命令执行成功，无输出)"
        return text

    return bash
