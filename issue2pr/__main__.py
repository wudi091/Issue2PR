"""入口：把各层组装起来，跑一个 issue。

这是**组装根**——全项目只有这里 import 具体实现（`LocalEnv`），
也只有这里决定「用哪个环境」。

两种跑法：

    # 本地试跑：issue 正文直接给，不碰 GitHub
    python -m issue2pr --repo <仓库路径> --issue "<issue 正文>"

    # Action：issue 从事件负载来，结论发布回 GitHub
    python -m issue2pr        # 读 $GITHUB_EVENT_PATH / $GITHUB_WORKSPACE / INPUT_*

实时打印工具调用用包装 handler 的方式做，所以 loop 层不需要知道「有人在看」。
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from collections.abc import Callable

from .action import make_client, publish, read_event
from .env import Env
from .env.local import LocalEnv
from .loop import AgentLoop
from .model import DEFAULT_BASE_URL, DEFAULT_MODEL, build_client
from .result import RESOLVED, RunResult
from .tools import build

PREVIEW_CHARS = 400
LINE = "-" * 70


def loud(handlers: dict[str, Callable[..., str]]) -> dict[str, Callable[..., str]]:
    """包一层 handler：跑之前打印命令，跑完打印观察结果的前几行。

    git 那些命令不经过这里（它们是 env 直调），所以推送用的 token 不会被打印。
    """

    def wrap(name: str, handler: Callable[..., str]) -> Callable[..., str]:
        def wrapped(**kwargs: object) -> str:
            arguments = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
            print(f"  → {name} {arguments}", flush=True)
            output = handler(**kwargs)
            preview = output[:PREVIEW_CHARS]
            if len(output) > PREVIEW_CHARS:
                preview += f"…（共 {len(output)} 字符）"
            print(textwrap.indent(preview, "    "), flush=True)
            return output

        return wrapped

    return {name: wrap(name, handler) for name, handler in handlers.items()}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="issue2pr", description="用一个 issue 驱动 Agent 改仓库")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_WORKSPACE", "."), help="仓库路径")
    parser.add_argument(
        "--issue", default=os.environ.get("INPUT_ISSUE"), help="issue 正文；给了就走本地模式"
    )
    parser.add_argument("--model", default=os.environ.get("INPUT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("INPUT_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--max-steps", type=int, default=int(os.environ.get("INPUT_MAX_STEPS", "20"))
    )
    return parser.parse_args(argv)


def _run_agent(
    env: Env, *, api_key: str, model: str, base_url: str, max_steps: int, issue_text: str
) -> RunResult:
    """两条路径共用的组装与执行。"""
    tools, handlers = build(env)
    loop = AgentLoop(
        build_client(api_key, base_url),
        model=model,
        tools=tools,
        handlers=loud(handlers),
        max_steps=max_steps,
    )

    print(f"仓库 : {env.cwd}")
    print(f"模型 : {model} @ {base_url}")
    print(f"预算 : {max_steps} 次模型调用")
    print(f"工具 : {[t['function']['name'] for t in tools]}")
    print(LINE, flush=True)

    result = loop.run(issue_text)

    print(LINE)
    print(f"结论 : {result.status}")
    print(f"原因 : {result.reason}")
    print(f"轨迹 : {len(result.messages)} 条消息")
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    api_key = os.environ.get("INPUT_API_KEY", "")
    if not api_key:
        print("缺少 INPUT_API_KEY（本地跑就设这个环境变量）", file=sys.stderr)
        return 2

    env = LocalEnv(args.repo)

    if args.issue:
        result = _run_agent(
            env,
            api_key=api_key,
            model=args.model,
            base_url=args.base_url,
            max_steps=args.max_steps,
            issue_text=args.issue,
        )
        return 0 if result.status == RESOLVED else 1

    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    token = os.environ.get("INPUT_GITHUB_TOKEN", "")
    if not event_path or not token:
        print(
            "Action 模式需要 $GITHUB_EVENT_PATH 和 INPUT_GITHUB_TOKEN；本地试跑请用 --issue",
            file=sys.stderr,
        )
        return 2

    issue = read_event(event_path)
    print(f"issue: #{issue.number} {issue.title} @ {issue.repo}（base {issue.base}）")
    result = _run_agent(
        env,
        api_key=api_key,
        model=args.model,
        base_url=args.base_url,
        max_steps=args.max_steps,
        issue_text=issue.text,
    )

    with make_client(token) as client:
        outcome = publish(
            env=env, issue=issue, result=result, client=client, token=token, model=args.model
        )
    print(f"发布 : {outcome.message}")
    return 0 if outcome.status == RESOLVED else 1


if __name__ == "__main__":
    raise SystemExit(main())
