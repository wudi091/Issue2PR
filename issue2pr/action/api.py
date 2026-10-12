"""调 GitHub REST API：开 PR、评论 issue。

用 httpx 而不是 gh CLI：openai 本来就带 httpx，容器里不用多装东西，
也不用再配一遍 gh 的认证。

这一层只认「说什么」，不认「从哪来」——repo / token 都是参数。
跟 `model.py` 一样，客户端由调用方造，测试就能塞一个 MockTransport 进去。
"""

from __future__ import annotations

import httpx

API = "https://api.github.com"
TIMEOUT = 30.0
ERROR_BODY_CHARS = 300


class ApiError(Exception):
    """GitHub 没接受这次调用。"""


def make_client(token: str) -> httpx.Client:
    """带认证的 GitHub 客户端。token 只在这里出现。"""
    return httpx.Client(
        base_url=API,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=TIMEOUT,
    )


def _post(client: httpx.Client, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    if response.status_code >= 300:
        raise ApiError(
            f"POST {path} 返回 {response.status_code}：{response.text[:ERROR_BODY_CHARS]}"
        )
    return response.json()


def open_pull_request(
    client: httpx.Client, *, repo: str, head: str, base: str, title: str, body: str
) -> str:
    """开 PR，返回它的网页地址。"""
    data = _post(
        client,
        f"/repos/{repo}/pulls",
        {"title": title, "head": head, "base": base, "body": body},
    )
    return data["html_url"]


def comment_on_issue(client: httpx.Client, *, repo: str, number: int, body: str) -> str:
    """在 issue 下评论，返回评论的网页地址。"""
    data = _post(client, f"/repos/{repo}/issues/{number}/comments", {"body": body})
    return data["html_url"]
