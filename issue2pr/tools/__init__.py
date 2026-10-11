"""工具层：模型能调什么，以及怎么把它调起来。

    dispatch.py  机制：绑定校验、执行一次调用
    bash.py      bash 工具

以后每加一个工具就加一个文件，在本文件里汇总。
"""

from __future__ import annotations

from typing import Callable

from openai.types.chat import ChatCompletionToolParam

from ..env import Env
from .bash import BASH_SCHEMA, make_bash_handler
from .dispatch import check_bindings, execute

__all__ = [
    "BASH_SCHEMA",
    "build",
    "check_bindings",
    "execute",
    "make_bash_handler",
]


def build(env: Env) -> tuple[list[ChatCompletionToolParam], dict[str, Callable[..., str]]]:
    """把当前所有工具装好，返回 (schemas, handlers)，可直接喂给 AgentLoop。

    这里是「有哪些工具」的唯一声明处——加工具只改这个函数和它引用的文件。
    """
    tools: list[ChatCompletionToolParam] = [BASH_SCHEMA]
    handlers: dict[str, Callable[..., str]] = {"bash": make_bash_handler(env)}
    check_bindings(tools, handlers)
    return tools, handlers
