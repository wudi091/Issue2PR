"""工具层的机制：schema 与实现的绑定校验、执行一次工具调用。

只负责「怎么把工具调起来」，不管具体有哪些工具（那些在隔壁每个文件里），
也不管循环跑了几步、什么时候停（那是 loop 的事）。

工具实现就是普通函数：收关键字参数、返回字符串（观察结果）。
要喊停就抛 TaskDone——那是唯一能让循环提前收工的信号。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from openai.types.chat import ChatCompletionToolParam

from ..result import TaskDone

log = logging.getLogger("issue2pr")


def check_bindings(
    tools: list[ChatCompletionToolParam], handlers: dict[str, Callable[..., str]]
) -> None:
    """每个工具 schema 都必须有实现，否则模型调了也没人接。"""
    unbound = [tool["function"]["name"] for tool in tools if tool["function"]["name"] not in handlers]
    if unbound:
        raise ValueError(f"这些工具只有 schema、没有实现：{unbound}")


def execute(handlers: dict[str, Callable[..., str]], name: str, arguments: str) -> tuple[str, bool]:
    """执行一次工具调用，返回 (观察结果, 是否失败)。

    工具自己的失败不往外抛：转成观察结果回填，让模型有机会自我修正。
    只有 TaskDone 例外——它要穿过去让循环收工。
    """
    try:
        args: Any = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("参数必须是 JSON 对象")
    except (json.JSONDecodeError, ValueError) as exc:
        return f"参数解析失败：{exc}", True

    handler = handlers.get(name)
    if handler is None:
        return f"没有这个工具：{name}", True

    try:
        return handler(**args), False
    except TaskDone:
        raise
    except Exception as exc:  # noqa: BLE001 —— 工具的任何失败都回填给模型，别让循环崩掉
        log.exception("工具 %s 执行失败", name)
        return f"工具执行失败：{type(exc).__name__}: {exc}", True
