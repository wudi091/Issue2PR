"""git 层的契约测试：真临时仓库，真跑 git。

仓库由 conftest 的 `git_repo` 夹具提供，不 mock。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from issue2pr.action import (
    GitError,
    branch_name,
    commit,
    commit_message,
    github_url,
    has_changes,
    push,
)
from issue2pr.env.local import LocalEnv


def test_branch_name_is_derived_from_the_issue_number() -> None:
    assert branch_name(12) == "issue2pr/issue-12"


def test_commit_message_carries_the_issue_title() -> None:
    message = commit_message(12, "median() 结果不对")

    assert message.startswith("fix: median() 结果不对")
    assert "#12" in message


def test_has_changes_is_false_on_a_fresh_checkout(git_repo: LocalEnv) -> None:
    assert has_changes(git_repo) is False


def test_nothing_is_committed_when_the_tree_is_clean(
    git_repo: LocalEnv, run_git: Callable[..., str]
) -> None:
    result = commit(git_repo, number=1, title="没改东西")

    assert result.committed is False
    head = run_git(git_repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    assert head == "main", "干净就不该建分支"


def test_the_change_lands_on_a_new_branch(
    git_repo: LocalEnv, run_git: Callable[..., str]
) -> None:
    (git_repo.cwd / "calc.py").write_text("x = 2\n", encoding="utf-8")

    result = commit(git_repo, number=7, title="median() 结果不对")

    assert result.committed is True
    assert result.branch == "issue2pr/issue-7"
    assert run_git(git_repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "issue2pr/issue-7"
    assert result.sha == run_git(git_repo, "rev-parse", "HEAD").strip()
    assert "x = 2" in run_git(git_repo, "show", "HEAD:calc.py")


def test_untracked_files_are_committed_too(
    git_repo: LocalEnv, run_git: Callable[..., str]
) -> None:
    """模型新建的文件必须进提交，否则开出来的 PR 是残的。"""
    (git_repo.cwd / "new_module.py").write_text("y = 1\n", encoding="utf-8")

    result = commit(git_repo, number=3, title="加个模块")

    assert result.committed is True
    assert "new_module.py" in run_git(git_repo, "show", "--stat", "HEAD")


def test_the_commit_is_made_as_the_bot(git_repo: LocalEnv, run_git: Callable[..., str]) -> None:
    """以 bot 名义提交是设计决定——顺带证明它盖过了仓库里原有的身份。"""
    (git_repo.cwd / "calc.py").write_text("x = 3\n", encoding="utf-8")

    commit(git_repo, number=1, title="改一下")

    assert run_git(git_repo, "log", "-1", "--format=%an <%ae>").strip() == (
        "github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>"
    )


def test_push_sends_the_branch_to_the_remote(
    git_repo: LocalEnv, run_git: Callable[..., str], tmp_path: Path
) -> None:
    bare = tmp_path / "remote.git"
    run_git(git_repo, "init", "--bare", "-b", "main", str(bare))
    (git_repo.cwd / "calc.py").write_text("x = 9\n", encoding="utf-8")
    result = commit(git_repo, number=5, title="修一下")

    push(git_repo, str(bare), result.branch)

    assert run_git(git_repo, "ls-remote", str(bare), f"refs/heads/{result.branch}").strip() != ""


def test_github_url_embeds_the_token() -> None:
    assert github_url("wudi091/x", "ghs_abc") == (
        "https://x-access-token:ghs_abc@github.com/wudi091/x.git"
    )


def test_a_failed_push_does_not_leak_the_token(
    git_repo: LocalEnv, run_git: Callable[..., str]
) -> None:
    """git 推送失败时会把整个 URL 打出来，那里面带着 token。

    用 127.0.0.1:1（没人监听）让 git 立刻失败，不走外网。
    """
    (git_repo.cwd / "calc.py").write_text("x = 4\n", encoding="utf-8")
    result = commit(git_repo, number=1, title="改一下")
    secret = "ghs_SUPERSECRET"

    url = f"https://x-access-token:{secret}@127.0.0.1:1/nope.git"
    with pytest.raises(GitError) as caught:
        push(git_repo, url, result.branch, secret=secret)

    assert secret not in str(caught.value)


def test_the_scrubber_rewrites_the_token_in_place() -> None:
    """上面那条是「结果保证」，这条是「机制」——git 未必每次都会自己打码。"""
    from issue2pr.action.git import _scrub

    assert _scrub("unable to access 'https://x-access-token:ghs_x@h/r.git'", "ghs_x") == (
        "unable to access 'https://x-access-token:***@h/r.git'"
    )
