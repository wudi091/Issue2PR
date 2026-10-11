"""模型层的契约测试：客户端怎么造、一次调用到底传了什么。

不联网：造客户端不会发请求，complete 用假客户端记录入参。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from issue2pr.model import DEFAULT_BASE_URL, DEFAULT_MODEL, build_client, complete


def test_client_defaults_to_deepseek() -> None:
    client = build_client("sk-test")

    assert str(client.base_url).rstrip("/") == DEFAULT_BASE_URL
    assert client.api_key == "sk-test"
    assert DEFAULT_MODEL == "deepseek-chat"


def test_client_accepts_a_custom_base_url() -> None:
    client = build_client("sk-test", base_url="http://localhost:9/v1")

    assert str(client.base_url).rstrip("/") == "http://localhost:9/v1"


def test_complete_passes_model_messages_and_tools() -> None:
    captured: dict[str, Any] = {}
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: captured.update(kwargs) or "sentinel")
        )
    )

    assert complete(fake, model="m", messages=[], tools=[]) == "sentinel"
    assert captured == {"model": "m", "messages": [], "tools": []}
