"""结论 → `$GITHUB_OUTPUT`。

GitHub 用这个文件在 step 之间传值，格式是一行一个 `key=value`。
多行值要写成 `key<<EOF ... EOF`，我们这两个值都是单行，先不做那套。
"""

from __future__ import annotations

import os
from pathlib import Path


def format_outputs(values: dict[str, str]) -> str:
    """拼成 `$GITHUB_OUTPUT` 要的格式。"""
    return "".join(f"{key}={value}\n" for key, value in values.items())


def write_outputs(values: dict[str, str], path: str | Path | None = None) -> bool:
    """**追加**写（GitHub 允许多次追加，覆盖会丢掉别的 step 的输出）。

    路径默认取 `$GITHUB_OUTPUT`。本地跑没这个环境变量，直接返回 False——
    输出文件是 Actions 独有的概念，本地没有不是错误。
    """
    raw = str(path) if path is not None else os.environ.get("GITHUB_OUTPUT", "")
    if not raw:
        return False
    with Path(raw).open("a", encoding="utf-8") as handle:
        handle.write(format_outputs(values))
    return True
