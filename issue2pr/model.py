"""模型层：跟模型打交道的全部细节。

循环不直接碰 openai 客户端——客户端怎么造、用哪个模型、一次调用怎么发，
都收在这一层。以后要加重试、用量统计、换供应商，只改这里。
"""

from __future__ import annotations

from openai import OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"


def build_client(api_key: str, base_url: str = DEFAULT_BASE_URL) -> OpenAI:
    """造一个客户端。DeepSeek 走 OpenAI 格式，所以只换 base_url。"""
    return OpenAI(api_key=api_key, base_url=base_url)


def complete(
    client: OpenAI,
    *,
    model: str,
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam],
) -> ChatCompletion:
    """发一次请求。以后的重试与用量统计都挂在这个函数里。"""
    return client.chat.completions.create(model=model, messages=messages, tools=tools)
