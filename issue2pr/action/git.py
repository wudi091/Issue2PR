"""把改动变成一次提交，再推成一个分支。

全部走 `env.exec`——git 就是个子进程，所以这一层能拿**真临时仓库**测，
不用 mock、不用联网。

这一层不认识 Issue：只收 number / title 这种原语，免得跟事件负载绑在一起。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..env import Env

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


class GitError(Exception):
    """git 没能完成我们要它做的事。"""


@dataclass(frozen=True)
class Commit:
    """一次提交的结果。工作区干净时 committed 为 False。"""

    committed: bool
    branch: str
    sha: str = ""


def branch_name(issue_number: int) -> str:
    return f"issue2pr/issue-{issue_number}"


def change_title(title: str) -> str:
    """提交标题，也是 PR 标题——两边说的是同一件事。"""
    return f"fix: {title}"


def commit_message(issue_number: int, title: str) -> str:
    return f"{change_title(title)}\n\n由 Issue2PR 自动生成（issue #{issue_number}）"


def github_url(repo: str, token: str) -> str:
    """带 token 的推送地址。

    容器里没有 credential helper，token 只能走 URL。代价是它会出现在进程
    命令行里——容器是临时的、`GITHUB_TOKEN` 跑完即失效，所以损失有上限。
    """
    return f"https://x-access-token:{token}@github.com/{repo}.git"


def _scrub(text: str, secret: str) -> str:
    """把 token 从任何要往外抛的文本里抹掉。

    git 推送失败时会把整个 URL 原样打出来，那里面带着 token。
    """
    return text.replace(secret, "***") if secret else text


def _run(env: Env, command: list[str], what: str, *, secret: str = "") -> str:
    result = env.exec(command)
    if not result.ok:
        raise GitError(f"{what}失败：{result.error}")
    completed = result.value
    if completed.returncode != 0:
        detail = _scrub((completed.stderr or completed.stdout or "").strip(), secret)
        raise GitError(f"{what}失败（exit {completed.returncode}）：{detail}")
    return completed.stdout or ""


def has_changes(env: Env) -> bool:
    """工作区有没有改动。`--porcelain` 连未跟踪文件一起算——模型新建的文件也要提交。"""
    return bool(_run(env, ["git", "status", "--porcelain"], "查工作区").strip())


def commit(env: Env, *, number: int, title: str) -> Commit:
    """把工作区改动提交到一个新分支上。"""
    branch = branch_name(number)
    if not has_changes(env):
        return Commit(committed=False, branch=branch)

    # 容器里的 git 没有身份，必须显式给。以 bot 名义提交是设计决定：
    # 代价是用 GITHUB_TOKEN 开的 PR 不会触发目标仓库自己的 CI（GitHub 防递归）。
    _run(env, ["git", "config", "user.name", BOT_NAME], "配置 git 身份")
    _run(env, ["git", "config", "user.email", BOT_EMAIL], "配置 git 身份")
    _run(env, ["git", "checkout", "-b", branch], "建分支")
    _run(env, ["git", "add", "-A"], "暂存改动")
    _run(env, ["git", "commit", "-m", commit_message(number, title)], "提交")
    sha = _run(env, ["git", "rev-parse", "HEAD"], "取提交哈希").strip()
    return Commit(committed=True, branch=branch, sha=sha)


def push(env: Env, url: str, branch: str, *, secret: str = "") -> None:
    """把当前 HEAD 推成 url 上的 branch。

    url 由调用方给：GitHub 那种带 token 的形式用 `github_url()` 拼，
    测试里可以直接给一个本地裸仓库路径。
    """
    _run(env, ["git", "push", url, f"HEAD:refs/heads/{branch}"], "推送分支", secret=secret)
