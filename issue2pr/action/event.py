"""事件负载 → 领域对象。

GitHub 把触发事件写成一份 JSON，路径放在 `$GITHUB_EVENT_PATH`。
这一层只干一件事：把它翻译成我们真正需要的几个字段——
别处不用知道那份 JSON 长什么样，也不用知道 `body` 可能是 null。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Issue:
    """一次要修的 issue，连同它所在的仓库。"""

    number: int
    title: str
    body: str
    repo: str  # "owner/name"
    base: str  # 仓库的默认分支，PR 要往这儿合

    @property
    def text(self) -> str:
        """给模型看的正文。标题也算内容——很多 issue 的信息全在标题里。"""
        return f"{self.title}\n\n{self.body}".strip()

    @property
    def owner(self) -> str:
        return self.repo.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.repo.split("/", 1)[1]


def parse_event(payload: dict) -> Issue:
    """从事件负载里取出 issue。

    字段缺了就直接抛 KeyError：宁可炸得响，也不要静默跑一个空 issue——
    那会变成一次「模型说没问题」的假成功。
    """
    issue = payload["issue"]
    repository = payload["repository"]
    return Issue(
        number=issue["number"],
        title=issue["title"],
        body=issue.get("body") or "",
        repo=repository["full_name"],
        base=repository["default_branch"],
    )


def read_event(path: str | Path) -> Issue:
    return parse_event(json.loads(Path(path).read_text(encoding="utf-8")))
