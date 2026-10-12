"""GitHub Action 集成层：输入从哪来、结果往哪去。

    event.py    事件负载 → issue 正文与仓库坐标
    outputs.py  结论 → $GITHUB_OUTPUT
    git.py      开分支、提交、push
    api.py      开 PR、评论 issue

这一层只有 Action 里用得到；本地跑直接走命令行参数，不碰它。
"""

from __future__ import annotations

from .api import ApiError, comment_on_issue, make_client, open_pull_request
from .event import Issue, parse_event, read_event
from .git import (
    Commit,
    GitError,
    branch_name,
    commit,
    commit_message,
    github_url,
    has_changes,
    push,
)
from .outputs import write_outputs
from .publish import Outcome, publish
from .report import Step, failure_comment, pr_body, steps_from

__all__ = [
    "ApiError",
    "Commit",
    "GitError",
    "Issue",
    "Outcome",
    "Step",
    "branch_name",
    "comment_on_issue",
    "commit",
    "commit_message",
    "failure_comment",
    "github_url",
    "has_changes",
    "make_client",
    "open_pull_request",
    "parse_event",
    "pr_body",
    "publish",
    "push",
    "read_event",
    "steps_from",
    "write_outputs",
]
