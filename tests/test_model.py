"""模型层的契约测试：客户端怎么造、一次调用发了什么、网关的壳怎么剥。

不联网，但**走真的 SDK 解析路径**：用 httpx.MockTransport 在 HTTP 层喂响应，
所以这里验证的行为和生产完全一致。

（用假的 SimpleNamespace 替掉 client 是不行的：SDK 解析响应用的是宽松构造，
`ChatCompletion.model_validate({"choices": None})` 会直接抛 ValidationError，
造不出生产里那个 `choices is None` 的状态。）
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from openai import OpenAI

from issue2pr.model import DEFAULT_BASE_URL, DEFAULT_MODEL, build_client, complete

PLAIN: dict[str, Any] = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 0,
    "model": "m",
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}
    ],
}


def client_returning(payload: dict[str, Any], sent: list[Any] | None = None) -> OpenAI:
    """造一个真 SDK 客户端，它的 HTTP 层被替换成固定响应。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    return OpenAI(
        api_key="sk-test",
        base_url="http://gateway.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_client_uses_the_configured_base_url_by_default() -> None:
    client = build_client("sk-test")

    assert str(client.base_url).rstrip("/") == DEFAULT_BASE_URL
    assert client.api_key == "sk-test"
    assert DEFAULT_MODEL, "默认模型名不能是空的"


def test_client_accepts_a_custom_base_url() -> None:
    client = build_client("sk-test", base_url="http://localhost:9/v1")

    assert str(client.base_url).rstrip("/") == "http://localhost:9/v1"


def test_complete_sends_model_messages_and_tools() -> None:
    sent: list[Any] = []

    complete(client_returning(PLAIN, sent), model="m", messages=[], tools=[])

    assert sent[0]["model"] == "m"
    assert sent[0]["messages"] == []
    assert sent[0]["tools"] == []


def test_a_standard_response_is_returned_untouched() -> None:
    result = complete(client_returning(PLAIN), model="m", messages=[], tools=[])

    assert result.choices[0].message.content == "hi"
    assert not result.model_extra, "标准响应不该多出任何字段"


def test_a_gateway_envelope_is_unwrapped() -> None:
    """gpt-load 的非流式分支会包一层 {"data": ..., "success": true}。"""
    enveloped = dict(PLAIN, choices=None, data=PLAIN, success=True)

    result = complete(client_returning(enveloped), model="m", messages=[], tools=[])

    assert result.choices[0].message.content == "hi"
    assert result.id == "chatcmpl-1"


def test_an_envelope_whose_data_is_not_an_object_is_left_alone() -> None:
    """壳在、但 data 不是对象时不动它——免得把畸形响应改成另一种畸形。"""
    malformed = dict(PLAIN, choices=None, data="不是对象")

    result = complete(client_returning(malformed), model="m", messages=[], tools=[])

    assert result.choices is None
