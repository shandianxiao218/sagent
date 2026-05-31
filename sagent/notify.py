from __future__ import annotations


def send_feishu_summary(text: str, env: dict[str, str]) -> dict:
    webhook = env.get("SAGENT_FEISHU_WEBHOOK", "")
    if not webhook:
        return {
            "ok": True,
            "mode": "skipped",
            "reason": "未配置 SAGENT_FEISHU_WEBHOOK，已跳过飞书推送。",
        }
    # 真正 HTTP 发送由 scripts/notify_feishu.py 负责；核心包保持测试可重复、无网络副作用。
    return {"ok": True, "mode": "configured", "message_preview": text[:120]}
