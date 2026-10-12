"""把一次运行的结果发布出去：开 PR，或者在 issue 下评论。

Action 的「后半场」——loop 跑完之后发生的所有事都在这里。
它只做编排，具体动作分别交给 git / api / report / outputs。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..env import Env
from ..result import RESOLVED, RunResult
from . import git, report
from .api import comment_on_issue, open_pull_request
from .event import Issue
from .outputs import write_outputs

NO_CHANGE = "Agent 判定已修复，但工作区没有任何改动，所以没有开 PR。"


@dataclass(frozen=True)
class Outcome:
    """发布结果：给退出码和日志用。"""

    status: str
    message: str
    pr_url: str = ""


def publish(
    *,
    env: Env,
    issue: Issue,
    result: RunResult,
    client: httpx.Client,
    token: str,
    model: str,
) -> Outcome:
    """按结论决定开 PR 还是评论。"""
    steps = report.steps_from(result.messages)

    if result.status != RESOLVED:
        return _comment(
            issue=issue,
            client=client,
            status=result.status,
            summary=result.reason,
            steps=steps,
            model=model,
        )

    change = git.commit(env, number=issue.number, title=issue.title)
    if not change.committed:
        # 模型说修好了，但一个字都没改。空 PR 没有意义，也不能算成功。
        return _comment(
            issue=issue,
            client=client,
            status="failed",
            summary=NO_CHANGE,
            steps=steps,
            model=model,
        )

    git.push(env, git.github_url(issue.repo, token), change.branch, secret=token)
    url = open_pull_request(
        client,
        repo=issue.repo,
        head=change.branch,
        base=issue.base,
        title=git.change_title(issue.title),
        body=report.pr_body(
            issue_number=issue.number, summary=result.reason, steps=steps, model=model
        ),
    )
    write_outputs({"status": "resolved", "pr_url": url})
    return Outcome(status="resolved", message=f"开了 PR：{url}", pr_url=url)


def _comment(
    *,
    issue: Issue,
    client: httpx.Client,
    status: str,
    summary: str,
    steps: list[report.Step],
    model: str,
) -> Outcome:
    comment_on_issue(
        client,
        repo=issue.repo,
        number=issue.number,
        body=report.failure_comment(
            issue_number=issue.number, summary=summary, steps=steps, model=model
        ),
    )
    write_outputs({"status": status})
    return Outcome(status=status, message=f"没开 PR，已在 issue 下评论（{status}）")
