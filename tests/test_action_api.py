"""api 层的契约测试：HTTP 层喂假响应，不联网。

跟 `test_model.py` 一个套路——用真的 `httpx.Client`，只把 transport 换掉，
所以请求的拼装、头、JSON 都是真的走了一遍。
"""

from __future__ import annotations

import json

import httpx
import pytest

from issue2pr.action.api import API, ApiError, comment_on_issue, make_client, open_pull_request


def client(handler) -> httpx.Client:
    return httpx.Client(base_url=API, transport=httpx.MockTransport(handler))


def test_open_pull_request_posts_what_github_expects() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/1"})

    with client(handler) as http:
        url = open_pull_request(
            http, repo="o/r", head="issue2pr/issue-1", base="main", title="fix: x", body="说明"
        )

    assert url == "https://github.com/o/r/pull/1"
    assert seen["method"] == "POST"
    assert seen["path"] == "/repos/o/r/pulls"
    assert seen["body"] == {
        "title": "fix: x",
        "head": "issue2pr/issue-1",
        "base": "main",
        "body": "说明",
    }


def test_comment_on_issue_posts_to_the_issue() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            201, json={"html_url": "https://github.com/o/r/issues/1#issuecomment-9"}
        )

    with client(handler) as http:
        url = comment_on_issue(http, repo="o/r", number=1, body="卡在测试上")

    assert seen["path"] == "/repos/o/r/issues/1/comments"
    assert seen["body"] == {"body": "卡在测试上"}
    assert url.endswith("#issuecomment-9")


def test_a_rejected_call_raises_with_the_status_and_body() -> None:
    """状态码和响应体都要带上——不然线上只能看到一句「失败了」。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Validation Failed"})

    with client(handler) as http:
        with pytest.raises(ApiError) as caught:
            open_pull_request(http, repo="o/r", head="h", base="main", title="t", body="b")

    assert "422" in str(caught.value)
    assert "Validation Failed" in str(caught.value)


def test_make_client_carries_the_token_and_the_api_version() -> None:
    """不发请求，直接看客户端装了什么头。"""
    with make_client("ghs_secret") as http:
        assert http.headers["authorization"] == "Bearer ghs_secret"
        assert http.headers["accept"] == "application/vnd.github+json"
        assert http.headers["x-github-api-version"] == "2022-11-28"
        assert str(http.base_url).rstrip("/") == API
