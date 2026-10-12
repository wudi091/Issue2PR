"""Action 集成层的契约测试：输入怎么进来、结果怎么出去。

全是纯函数加一个文件读写，不联网、不碰 git。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from issue2pr.action import parse_event, read_event, write_outputs
from issue2pr.action.outputs import format_outputs

# 真实事件负载的形状（截到我们用到的那几个字段）
PAYLOAD = {
    "action": "opened",
    "issue": {
        "number": 7,
        "title": "median() 对偶数个元素返回错误结果",
        "body": ">>> median([1, 2, 3, 4])\n3",
        "state": "open",
    },
    "repository": {
        "full_name": "wudi091/issue2pr-sandbox",
        "name": "issue2pr-sandbox",
        "default_branch": "main",
        "owner": {"login": "wudi091"},
    },
}


def test_parse_event_pulls_out_what_we_need() -> None:
    issue = parse_event(PAYLOAD)

    assert issue.number == 7
    assert issue.title == "median() 对偶数个元素返回错误结果"
    assert issue.repo == "wudi091/issue2pr-sandbox"


def test_owner_and_name_split_the_repo() -> None:
    issue = parse_event(PAYLOAD)

    assert issue.owner == "wudi091"
    assert issue.name == "issue2pr-sandbox"


def test_the_default_branch_becomes_the_pr_base() -> None:
    """PR 要往仓库自己的默认分支合，不能写死 main。"""
    payload = {
        **PAYLOAD,
        "repository": {**PAYLOAD["repository"], "default_branch": "develop"},
    }

    assert parse_event(payload).base == "develop"


def test_a_null_body_becomes_an_empty_string() -> None:
    """GitHub 对没有正文的 issue 给的是 null，不是空串。"""
    payload = {**PAYLOAD, "issue": {**PAYLOAD["issue"], "body": None}}

    assert parse_event(payload).body == ""


def test_issue_text_is_title_then_body() -> None:
    issue = parse_event(PAYLOAD)

    assert issue.text.startswith("median() 对偶数个元素返回错误结果")
    assert issue.text.endswith("3")


def test_issue_text_survives_a_missing_body() -> None:
    payload = {**PAYLOAD, "issue": {**PAYLOAD["issue"], "body": None}}

    assert parse_event(payload).text == "median() 对偶数个元素返回错误结果"


def test_a_payload_without_an_issue_fails_loudly() -> None:
    """宁可炸得响，也不要静默跑一个空 issue——那会变成一次假成功。"""
    with pytest.raises(KeyError):
        parse_event({"action": "opened"})


def test_read_event_reads_the_json_file(tmp_path: Path) -> None:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(PAYLOAD, ensure_ascii=False), encoding="utf-8")

    assert read_event(path).number == 7


def test_format_outputs_is_one_key_per_line() -> None:
    assert format_outputs({"status": "resolved", "pr_url": "https://x/1"}) == (
        "status=resolved\npr_url=https://x/1\n"
    )


def test_write_outputs_appends_and_keeps_what_was_there(tmp_path: Path) -> None:
    """覆盖写会丢掉别的 step 的输出，必须追加。"""
    path = tmp_path / "output"
    path.write_text("earlier=1\n", encoding="utf-8")

    assert write_outputs({"status": "resolved"}, path) is True
    assert path.read_text(encoding="utf-8") == "earlier=1\nstatus=resolved\n"


def test_write_outputs_without_a_path_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地跑没有 $GITHUB_OUTPUT，那不是错误。"""
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    assert write_outputs({"status": "resolved"}) is False


def test_write_outputs_uses_the_env_var_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))

    assert write_outputs({"status": "failed"}) is True
    assert path.read_text(encoding="utf-8") == "status=failed\n"
