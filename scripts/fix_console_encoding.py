#!/usr/bin/env python3
"""Windows 终端编码修复工具。

解决 PowerShell 下 Python 输出中文乱码问题。
使用方法：
  1. 在 PowerShell 中运行：
     python scripts/fix_console_encoding.py
  2. 或在 PowerShell profile 中添加：
     chcp 65001 > $null
     $env:PYTHONIOENCODING = "utf-8"

原理：
  - Windows PowerShell 默认使用 GBK (code page 936)
  - Python 默认使用控制台编码输出
  - 当 Python 输出 UTF-8 中文时，PowerShell 无法正确显示
  - 解决方案：设置控制台为 UTF-8 (code page 65001)
"""

from __future__ import annotations

import os
import sys


def fix_console() -> dict:
    """修复 Windows 控制台编码。返回修复结果。"""
    result: dict = {"platform": sys.platform}

    if sys.platform != "win32":
        result["status"] = "skipped"
        result["reason"] = "非 Windows 平台，无需修复"
        return result

    import locale

    # 当前状态
    result["console_cp"] = locale.getpreferredencoding()
    result["stdout_encoding"] = getattr(sys.stdout, "encoding", "unknown")

    # 设置环境变量
    os.environ["PYTHONIOENCODING"] = "utf-8"
    result["pythonioencoding_set"] = True

    # 设置 stdout 编码
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            result["stdout_reconfigured"] = True
        except Exception as e:
            result["stdout_reconfigured"] = str(e)
    else:
        result["stdout_reconfigured"] = False

    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            result["stderr_reconfigured"] = True
        except Exception as e:
            result["stderr_reconfigured"] = str(e)
    else:
        result["stderr_reconfigured"] = False

    # 测试中文输出
    test_str = "sagent 终端编码修复 ✓"
    result["test_output"] = test_str
    result["status"] = "ok"

    return result


def main() -> None:
    result = fix_console()
    print(f"状态: {result['status']}")
    if result["status"] == "ok":
        print(f"控制台编码: {result.get('console_cp')}")
        print(f"stdout 编码: {result.get('stdout_encoding')}")
        print(f"测试: {result.get('test_output')}")
        print("\n如需永久修复，请在 PowerShell profile 中添加：")
        print("  chcp 65001 > $null")
        print('  $env:PYTHONIOENCODING = "utf-8"')
    elif result["status"] == "skipped":
        print(result["reason"])


if __name__ == "__main__":
    main()
