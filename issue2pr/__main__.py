"""入口：把各层组装起来，跑一个 issue。

这是**组装根**——全项目只有这里 import 具体实现（`LocalEnv`），
也只有这里决定"用哪个环境"。其他层只认协议，不知道具体实现存在。

本地试跑：

    python -m issue2pr --repo <仓库路径> --issue "<issue 正文>"

在 GitHub Action 里由 action.yml 调起，配置从 INPUT_* 环境变量读。

这里还负责**实时打印工具调用**——用包装 handler 的方式做，
所以 loop 层完全不需要知道"有人在看"。
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from typing import Callable

from .env.local import LocalEnv
from .loop import AgentLoop
from .model import DEFAULT_BASE_URL, DEFAULT_MODEL, build_client
from .tools import build

PREVIEW_CHARS = 400


def loud(handlers: dict[str, Callable[..., str]]) -> dict[str, Callable[..., str]]:
    """包一层 handler：跑之前打印命令，跑完打印观察结果的前几行。"""

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="issue2pr", description="用一个 issue 驱动 Agent 改仓库")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_WORKSPACE", "."), help="仓库路径")
    parser.add_argument("--issue", default=os.environ.get("INPUT_ISSUE"), help="issue 正文")
    parser.add_argument("--model", default=os.environ.get("INPUT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("INPUT_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("INPUT_MAX_STEPS", "20")))
    args = parser.parse_args(argv)

    api_key = os.environ.get("INPUT_API_KEY", "")
    if not api_key:
        print("缺少 INPUT_API_KEY（本地跑就 export INPUT_API_KEY=...）", file=sys.stderr)
        return 2
    if not args.issue:
        print("缺少 issue 正文：用 --issue 传，或设 INPUT_ISSUE", file=sys.stderr)
        return 2

    env = LocalEnv(args.repo)
    tools, handlers = build(env)
    loop = AgentLoop(
        build_client(api_key, args.base_url),
        model=args.model,
        tools=tools,
        handlers=loud(handlers),
        max_steps=args.max_steps,
    )

    print(f"仓库 : {env.cwd}")
    print(f"模型 : {args.model} @ {args.base_url}")
    print(f"预算 : {args.max_steps} 次模型调用")
    print(f"工具 : {[t['function']['name'] for t in tools]}")
    print("-" * 70, flush=True)

    result = loop.run(args.issue)

    print("-" * 70)
    print(f"结论 : {result.status}")
    print(f"原因 : {result.reason}")
    print(f"轨迹 : {len(result.messages)} 条消息")
    return 0 if result.status == "resolved" else 1


if __name__ == "__main__":
    raise SystemExit(main())
