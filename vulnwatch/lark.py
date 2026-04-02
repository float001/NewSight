from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .config import LarkConfig

log = logging.getLogger("vulnwatch.lark")


def _post_webhook(lark: LarkConfig, payload: dict[str, Any]) -> bool:
    if not lark.enabled:
        log.info("Lark disabled, skip send")
        return True
    webhook = lark.resolved_webhook
    if not webhook:
        log.warning("Lark enabled but webhook missing")
        return False
    try:
        r = requests.post(webhook, data=json.dumps(payload), headers={"Content-Type": "application/json"}, timeout=20)
    except requests.RequestException as e:
        log.warning("Lark send error: %s", e)
        return False
    ok = r.status_code < 400
    # best-effort log response on failure
    if not ok:
        try:
            log.warning("Lark send failed http=%s body=%s", r.status_code, (r.text or "")[:800])
        except Exception:
            log.warning("Lark send failed http=%s", r.status_code)
    else:
        log.info("Lark send ok http=%s", r.status_code)
    return ok


def send_lark_text(lark: LarkConfig, text: str) -> bool:
    payload = {"msg_type": "text", "content": {"text": text}}
    return _post_webhook(lark, payload)


def send_lark_card(
    lark: LarkConfig,
    *,
    title: str,
    date_str: str,
    count_items: int,
) -> bool:
    # Feishu/Lark interactive card: nicer formatting than plain text.
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**时间**\n{date_str}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**资讯**\n{count_items} 条"}},
            ],
        },
    ]

    card = {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": title}},
        "elements": elements,
    }
    payload = {"msg_type": "interactive", "card": card}
    ok = _post_webhook(lark, payload)
    if ok:
        return True
    # fallback to text
    fallback = "\n".join(
        [
            f"{title}",
            f"- 时间：{date_str}",
            f"- 资讯：{count_items} 条",
        ]
    ).strip()
    return send_lark_text(lark, fallback)

