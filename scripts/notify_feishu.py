#!/usr/bin/env python3
"""飞书机器人通知入口。

通过环境变量 SAGENT_FEISHU_WEBHOOK 读取飞书自定义机器人 webhook。
默认发送 text 消息；如果未配置 webhook，则安全跳过并返回 skipped 状态。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any


def build_payload(text: str) -> dict[str, Any]:
    return {
        "msg_type": "text",
        "content": {"text": text},
    }


def post_json(url: str, payload: dict[str, Any], timeout: int) -> tuple[int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.status, body


def main() -> None:
    parser = argparse.ArgumentParser(description="发送 sagent 飞书通知")
    parser.add_argument("--text", required=True, help="通知正文")
    parser.add_argument("--title", default="sagent 扫描结果", help="通知标题")
    parser.add_argument(
        "--webhook",
        default=os.getenv("SAGENT_FEISHU_WEBHOOK", ""),
        help="飞书 webhook；默认读取环境变量",
    )
    parser.add_argument("--timeout", type=int, default=10, help="HTTP 超时时间（秒）")
    parser.add_argument("--dry-run", action="store_true", help="只构造消息，不实际发送")
    args = parser.parse_args()

    message = f"{args.title}\n\n{args.text}\n\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n风险提示：仅作研究和辅助分析，不构成投资建议。"
    payload = build_payload(message)

    if args.dry_run:
        print(
            json.dumps(
                {"ok": True, "mode": "dry-run", "payload": payload},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if not args.webhook:
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "skipped",
                    "reason": "未配置 SAGENT_FEISHU_WEBHOOK，已跳过飞书推送。",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    try:
        status, body = post_json(args.webhook, payload, args.timeout)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {"ok": False, "status": error.code, "error": body},
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)
    except Exception as error:  # noqa: BLE001 - CLI 入口需要把异常序列化给 extension
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2)
        )
        sys.exit(1)

    print(
        json.dumps(
            {"ok": 200 <= status < 300, "status": status, "response": body},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
