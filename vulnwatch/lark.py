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


def _clip_md(s: str, *, limit: int) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 12)].rstrip() + "\n\n...(已截断)"


def _strip_leading_title(s: str, titles: list[str]) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    lines = [ln.rstrip() for ln in s.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip() in {t.strip() for t in titles if t.strip()}:
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def send_lark_card(
    lark: LarkConfig,
    *,
    title: str,
    date_str: str,
    count_items: int,
    vuln_intel: str,
    security_posture: str,
) -> bool:
    # Feishu/Lark interactive card: nicer formatting than plain text.
    vuln_intel = _strip_leading_title(vuln_intel, ["今日漏洞（情报）", "今日漏洞", "今日漏洞：", "今日漏洞（情报）："])
    security_posture = _strip_leading_title(security_posture, ["今日安全态势总结", "今日安全态势总结："])
    vuln_intel = _clip_md(vuln_intel, limit=2400)
    security_posture = _clip_md(security_posture, limit=2400)

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**日期**\n{date_str}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**资讯**\n{count_items} 条"}},
            ],
        },
        {"tag": "hr"},
    ]

    if vuln_intel:
        elements.extend(
            [
                {"tag": "div", "text": {"tag": "lark_md", "content": "**今日漏洞（情报）**"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": vuln_intel}},
                {"tag": "hr"},
            ]
        )
    if security_posture:
        elements.extend(
            [
                {"tag": "div", "text": {"tag": "lark_md", "content": "**今日安全态势总结**"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": security_posture}},
            ]
        )

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
    vuln_intel_fb = _strip_leading_title(vuln_intel, ["今日漏洞（情报）", "今日漏洞", "今日漏洞：", "今日漏洞（情报）："])
    security_posture_fb = _strip_leading_title(security_posture, ["今日安全态势总结", "今日安全态势总结："])
    fallback = "\n".join(
        [
            f"{title}",
            f"- 日期：{date_str}",
            f"- 资讯：{count_items} 条",
            (("\n今日漏洞：\n" + vuln_intel_fb) if vuln_intel_fb else ""),
            (("\n今日安全态势总结：\n" + security_posture_fb) if security_posture_fb else ""),
        ]
    ).strip()
    return send_lark_text(lark, fallback)

