"""环境层契约：工具访问文件系统的唯一入口。

规矩（学 pi）：方法失败**不抛异常**，把失败编码进返回值。
这样工具层不用写 try/except——失败是数据，不是控制流。

    __init__.py  本文件：契约（Result / EnvError / Env 协议），不碰磁盘
    local.py     本地实现：真实磁盘 + 真实子进程

本文件谁都不依赖；实现依赖本文件。所以这里不能 import 任何实现，
否则分层就倒了。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class EnvError(Exception):
    """只有 unwrap() 取不到值时才抛——env 的方法本身从不抛异常。"""


@dataclass(frozen=True)
class Result:
    """要么有值、要么有错误，不会两者都有。"""

    value: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def unwrap(self) -> Any:
        """确定不会失败时用它取值；失败就抛 EnvError。"""
        if self.error is not None:
            raise EnvError(self.error)
        return self.value


def ok(value: Any = None) -> Result:
    return Result(value=value)


def err(message: str) -> Result:
    return Result(error=message)


class Env(Protocol):
    """环境接口。换实现（本地 / 容器 / 远程）时保持同一套方法签名，工具层不用改。"""

    cwd: Path

    def absolute_path(self, path: str) -> Result: ...

    def exists(self, path: str) -> Result: ...

    def read_text(self, path: str) -> Result: ...

    def list_dir(self, path: str) -> Result: ...

    def exec(
        self, command: str | list[str], *, cwd: str | None = None, timeout: float = 120.0
    ) -> Result: ...
