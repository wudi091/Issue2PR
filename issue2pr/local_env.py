"""环境层的本地实现：真实磁盘。

路径安全在这里兜住——absolute_path 拒绝逃出 cwd 的路径。
pi 不做这件事（它靠容器隔离），但我们的路径是模型给的、不可控，多一层检查值得。
"""

from __future__ import annotations

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
