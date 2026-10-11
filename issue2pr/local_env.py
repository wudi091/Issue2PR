"""环境层的本地实现：真实磁盘。

路径安全在这里兜住——absolute_path 拒绝逃出 cwd 的路径。
pi 不做这件事（它靠容器隔离），但我们的路径是模型给的、不可控，多一层检查值得。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .env import Result, err, ok


class LocalEnv:
    """本地文件系统环境。"""

    def __init__(self, cwd: str | Path) -> None:
        self.cwd = Path(cwd).resolve()

    def absolute_path(self, path: str) -> Result:
        """把相对路径解析成绝对路径，并拒绝逃出 cwd 的路径。

        不要求路径存在（调用方可能只是在拼一个待创建的路径），
        但会解析符号链接，所以软链逃逸也拦得住。
        """
        candidate = Path(path)
        resolved = (candidate if candidate.is_absolute() else self.cwd / candidate).resolve()
        if resolved != self.cwd and self.cwd not in resolved.parents:
            return err(f"路径越界，拒绝访问工作目录之外：{path}")
        return ok(resolved)

    def exists(self, path: str) -> Result:
        resolved = self.absolute_path(path)
        if not resolved.ok:
            return resolved
        return ok(resolved.value.exists())

    def read_text(self, path: str) -> Result:
        resolved = self.absolute_path(path)
        if not resolved.ok:
            return resolved
        target = resolved.value
        if not target.is_file():
            return err(f"不是文件：{path}")
        try:
            return ok(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            return err(f"读取失败：{path}：{exc}")

    def list_dir(self, path: str = ".") -> Result:
        """列出一层目录。目录名带尾斜杠，让模型一眼看出哪些能继续往下走。"""
        resolved = self.absolute_path(path)
        if not resolved.ok:
            return resolved
        target = resolved.value
        if not target.is_dir():
            return err(f"不是目录：{path}")
        try:
            entries = sorted(f"{item.name}/" if item.is_dir() else item.name for item in target.iterdir())
        except OSError as exc:
            return err(f"列目录失败：{path}：{exc}")
        return ok(entries)

    def exec(
        self, command: str | list[str], *, cwd: str | None = None, timeout: float = 120.0
    ) -> Result:
        """跑一个命令，返回 stdlib 的 CompletedProcess。

        command 传**字符串**就走 shell（管道、&&、重定向都能用）；
        传**列表**就直接执行，不经 shell，参数不会被解析。

        **退出码非 0 不是错误**——那是命令的正常结果（grep 没匹配就退 1），
        调用方看 `.returncode`。只有命令不存在、超时、起不来才算 Result.error。

        已知问题：超时只杀**直接子进程**。走 shell 时命令是 shell 的子进程，
        而 Windows 的 cmd 不会 exec 掉自己，所以孙进程会活下来——
        tests/test_bash_tool.py 里那个超时用例要等满 sleep 才返回就是这个原因。
        Linux 上 sh 对单条命令会 exec，通常没这个问题，但管道和 && 不保证。
        """
        workdir = self.absolute_path(cwd) if cwd else ok(self.cwd)
        if not workdir.ok:
            return workdir

        shown = command if isinstance(command, str) else " ".join(command)
        try:
            completed = subprocess.run(
                command,
                cwd=workdir.value,
                shell=isinstance(command, str),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return err(f"命令超时（{timeout:g} 秒）：{shown}")
        except FileNotFoundError as exc:
            return err(f"命令不存在：{exc}")
        except OSError as exc:
            return err(f"命令启动失败：{shown}：{exc}")
        return ok(completed)
