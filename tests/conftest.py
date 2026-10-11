"""测试夹具。

**为什么覆盖 pytest 内置的 `tmp_path`**：本机环境下，pytest 在系统临时目录
（`%TEMP%\\pytest-of-<user>`）里创建的目录会在创建后变成不可读，
之后每次运行都在 setup 阶段报 `PermissionError: [WinError 5]`。

这里用同名夹具覆盖内置版本：对测试代码语义完全一致，
但临时目录落在仓库内 `tests/.tmp/` 下，用完即删，不依赖系统临时目录。
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """覆盖 pytest 内置夹具：语义一致，位置改到仓库内。"""
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TMP_ROOT / uuid.uuid4().hex[:12]
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
