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

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "http://s1:3001/v1"


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
    """发一次请求。以后的重试与用量统计都挂在这个函数里。

    有的网关（实测 gpt-load 的**非流式**分支）会在标准响应外面再包一层
    `{"data": {...}, "success": true}`。SDK 在顶层找不到 choices，会把整层壳
    塞进 `model_extra`，于是 `completion.choices` 是 None。

    这里剥掉。只在真看到那层壳时才动手，标准响应原样返回——
    所以换成真 DeepSeek 或任何标准网关都不受影响。
    """
    completion = client.chat.completions.create(model=model, messages=messages, tools=tools)
    envelope = completion.model_extra or {}
    if completion.choices is None and isinstance(envelope.get("data"), dict):
        return ChatCompletion.model_validate(envelope["data"])
    return completion
