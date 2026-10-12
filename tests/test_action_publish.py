"""publish 层的契约测试：真 git 仓库 + 假 GitHub。

这一层是 Action 的收口，所以测的是「什么情况下开 PR、什么情况下只评论」。
推送被拦掉了——`git.push` 自己有真裸仓库的测试，这里只关心有没有走到它。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from issue2pr.action.api import API
from issue2pr.action.event import Issue
from issue2pr.action.publish import NO_CHANGE, publish
from issue2pr.env.local import LocalEnv
from issue2pr.result import BUDGET_EXHAUSTED, RESOLVED, RunResult

ISSUE = Issue(
    number=7, title="median() 结果不对", body="偶数个元素时不对", repo="o/r", base="main"
)


class FakeGitHub:
    """把请求记下来，按路径给一个像样的响应。"""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/9"})
        return httpx.Response(
            201, json={"html_url": "https://github.com/o/r/issues/7#issuecomment-1"}
        )

    @property
    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]

    @property
    def bodies(self) -> list[dict]:
        return [body for _, body in self.requests]


def transcript() -> list[dict]:
    return [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "median 不对"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command": "python -m pytest -q"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "15 passed in 0.02s"},
        {"role": "assistant", "content": "改好了"},
    ]


def result(status: str, reason: str = "改好了") -> RunResult:
    return RunResult(status=status, reason=reason, messages=transcript())


@pytest.fixture
def outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))
    return path


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def client(github: FakeGitHub) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API, transport=httpx.MockTransport(github.handler)) as http:
        yield http


@pytest.fixture
def pushed(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """拦掉真推送：不拦的话 publish 会去连 github.com。"""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "issue2pr.action.git.push", lambda env, url, branch, **kwargs: calls.append((url, branch))
    )
    return calls


def test_a_resolved_run_opens_a_pull_request(
    git_repo: LocalEnv,
    github: FakeGitHub,
    client: httpx.Client,
    outputs: Path,
    pushed: list[tuple[str, str]],
) -> None:
    (git_repo.cwd / "calc.py").write_text("x = 2\n", encoding="utf-8")

    outcome = publish(
        env=git_repo,
        issue=ISSUE,
        result=result(RESOLVED),
        client=client,
        token="ghs_x",
        model="deepseek-flash",
    )

    assert outcome.status == "resolved"
    assert outcome.pr_url == "https://github.com/o/r/pull/9"
    assert github.paths == ["/repos/o/r/pulls"]
    assert len(pushed) == 1, "开 PR 之前必须先推送分支"

    payload = github.bodies[0]
    assert payload["head"] == "issue2pr/issue-7"
    assert payload["base"] == "main", "要往仓库自己的默认分支合"
    assert payload["title"] == "fix: median() 结果不对"
    assert "python -m pytest -q" in payload["body"], "PR 描述里要有它跑过的命令"
    assert "15 passed in 0.02s" in payload["body"]
    assert "没有独立验证" in payload["body"]

    assert outputs.read_text(encoding="utf-8") == (
        "status=resolved\npr_url=https://github.com/o/r/pull/9\n"
    )


def test_a_failed_run_only_comments(
    git_repo: LocalEnv,
    github: FakeGitHub,
    client: httpx.Client,
    outputs: Path,
    pushed: list[tuple[str, str]],
) -> None:
    outcome = publish(
        env=git_repo,
        issue=ISSUE,
        result=result(BUDGET_EXHAUSTED, "步数预算用完"),
        client=client,
        token="ghs_x",
        model="m",
    )

    assert outcome.status == BUDGET_EXHAUSTED
    assert github.paths == ["/repos/o/r/issues/7/comments"]
    assert "步数预算用完" in github.bodies[0]["body"]
    assert "没有开 PR" in github.bodies[0]["body"]
    assert pushed == []
    assert outputs.read_text(encoding="utf-8") == f"status={BUDGET_EXHAUSTED}\n"


def test_a_resolved_run_with_no_changes_only_comments(
    git_repo: LocalEnv,
    github: FakeGitHub,
    client: httpx.Client,
    outputs: Path,
    pushed: list[tuple[str, str]],
) -> None:
    """模型说修好了，但工作区一个字都没改——不能开空 PR，也不能算成功。"""
    outcome = publish(
        env=git_repo,
        issue=ISSUE,
        result=result(RESOLVED),
        client=client,
        token="ghs_x",
        model="m",
    )

    assert outcome.status == "failed"
    assert outcome.pr_url == ""
    assert github.paths == ["/repos/o/r/issues/7/comments"]
    assert NO_CHANGE in github.bodies[0]["body"]
    assert pushed == []
    assert outputs.read_text(encoding="utf-8") == "status=failed\n"
