from __future__ import annotations

import json
from dataclasses import dataclass
import logging
import re
import time
from typing import Optional

import requests

from .config import AIConfig

log = logging.getLogger("vulnwatch.ai")


@dataclass(frozen=True)
class AIClassified:
    kind: str  # "vuln" | "security" | "ignore"
    short_reason: str


@dataclass(frozen=True)
class AIAggregation:
    vuln_intel: str
    security_posture: str


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _truncate(s: str, n: int = 2000) -> str:
    s = s or ""
    return s if len(s) <= n else (s[:n] + f"...(truncated {len(s)-n} chars)")


def _safe_messages_preview(messages: list[dict]) -> list[dict]:
    """
    仅用于 debug 日志：截断 content，避免日志爆炸。
    不在此处做敏感信息清洗（key 在 header 里，不会输出）。
    """
    out: list[dict] = []
    for m in messages or []:
        role = (m or {}).get("role")
        content = (m or {}).get("content")
        out.append({"role": role, "content": _truncate(str(content), 800)})
    return out


def _extract_json_candidate(text: str) -> str:
    """
    DeepSeek/LLM 可能返回：
    - ```json ... ``` 代码块
    - 前后夹杂说明文字
    尝试抽取最可能的 JSON 片段用于 json.loads。
    """
    t = (text or "").strip()
    if not t:
        return ""
    m = _JSON_FENCE_RE.search(t)
    if m:
        inner = (m.group(1) or "").strip()
        if inner:
            return inner
    # 尝试找第一个数组或对象的起止
    start_candidates = [i for i in (t.find("["), t.find("{")) if i != -1]
    if not start_candidates:
        return t
    start = min(start_candidates)
    end_candidates = [i for i in (t.rfind("]"), t.rfind("}")) if i != -1]
    end = max(end_candidates) if end_candidates else len(t) - 1
    if end > start:
        return t[start : end + 1].strip()
    return t


def _chat_completions(ai: AIConfig, messages: list[dict], *, max_tokens: int = 900) -> str:
    if not ai.enabled:
        return ""
    key = ai.resolved_api_key
    if not key:
        log.warning("AI enabled but api key missing (env=%s)", ai.api_key_env)
        return ""
    url = f"{ai.base_url}/chat/completions"
    body = {
        "model": ai.model,
        "messages": messages,
        "temperature": 0.2,
    }
    t0 = time.time()
    try:
        # 去掉 token 限制参数（max_tokens），让服务端按默认策略生成
        log.info("AI request model=%s", ai.model)
        if log.isEnabledFor(logging.DEBUG):
            log.debug("AI request url=%s body=%s", url, json.dumps({**body, "messages": _safe_messages_preview(messages)}, ensure_ascii=False))
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=ai.timeout_s,
        )
    except requests.RequestException as e:
        log.warning("AI request error: %s", e)
        return ""
    dt_ms = int((time.time() - t0) * 1000)
    if r.status_code >= 400:
        if log.isEnabledFor(logging.DEBUG):
            log.debug("AI response http=%s elapsed_ms=%s text=%s", r.status_code, dt_ms, _truncate(r.text, 2000))
        log.warning("AI http=%s elapsed_ms=%s", r.status_code, dt_ms)
        return ""
    try:
        j = r.json()
    except Exception:
        if log.isEnabledFor(logging.DEBUG):
            log.debug("AI response http=%s elapsed_ms=%s text=%s", r.status_code, dt_ms, _truncate(r.text, 2000))
        log.warning("AI invalid json elapsed_ms=%s", dt_ms)
        return ""
    if log.isEnabledFor(logging.DEBUG):
        log.debug("AI response http=%s elapsed_ms=%s json=%s", r.status_code, dt_ms, _truncate(json.dumps(j, ensure_ascii=False), 4000))
    content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    log.info("AI ok elapsed_ms=%s out_chars=%s", dt_ms, len(content or ""))
    return content


def classify_titles_batch(ai: AIConfig, titles: list[str]) -> list[AIClassified]:
    """
    titles: [title, ...]
    Return same-length list.
    """
    if not titles:
        return []
    prompt_lines = [
        "你是一名安全情报分拣助手。输入的标题可能包含中文或英文（或混合），只根据标题判断分类：",
        "- vuln：明确漏洞/补丁/PoC/Exploit/CVE/0day/RCE/提权/绕过/注入/越界/内存破坏/漏洞利用相关",
        "- security：安全事件/攻防/恶意软件/勒索/钓鱼/供应链投毒/数据泄露/云安全/身份与权限/安全研究/检测与防护等（非具体漏洞也可）",
        "- ignore：与安全无关（招聘、课程、抽奖、泛技术新闻等）",
        "",
        "提示：英文标题也要识别常见安全关键词，例如：vulnerability, exploit, patch, advisory, CVE, 0-day/zero-day, RCE, XSS, SSRF, SQLi, auth bypass, privilege escalation, malware, ransomware, phishing, APT, IOC, supply chain, data breach。",
        "",
        "对下面每一条输出严格 JSON 数组，每个元素结构：",
        '{"kind":"vuln|security|ignore","reason":"<=20字"}',
        "数组长度必须与输入条目数一致，顺序一致。",
        "",
        "输入条目：",
    ]
    for i, t in enumerate(titles, start=1):
        prompt_lines.append(f"{i}. 标题：{t}")
    log.info("AI classify batch size=%s", len(titles))
    out = _chat_completions(ai, [{"role": "user", "content": "\n".join(prompt_lines)}], max_tokens=500).strip()
    try:
        arr = json.loads(_extract_json_candidate(out))
        res: list[AIClassified] = []
        for obj in arr:
            kind = str((obj or {}).get("kind", "ignore")).strip()
            reason = str((obj or {}).get("reason", "")).strip()
            if kind not in ("vuln", "security", "ignore"):
                kind = "ignore"
            res.append(AIClassified(kind=kind, short_reason=reason[:50]))
        if len(res) != len(titles):
            raise ValueError("length mismatch")
        return res
    except Exception:
        # fallback: per-item
        log.warning("AI batch parse failed, fallback per-item size=%s", len(titles))
        return [classify_title(ai, t) for t in titles]


def classify_title(ai: AIConfig, title: str) -> AIClassified:
    prompt = f"""你是一名安全情报分拣助手。输入标题可能是中文或英文（或混合），只根据标题判断分类：
- vuln：明确漏洞/补丁/PoC/Exploit/CVE/0day/RCE/提权/绕过/注入/越界/内存破坏/漏洞利用相关
- security：安全事件/攻防/恶意软件/勒索/钓鱼/供应链投毒/数据泄露/云安全/身份与权限/安全研究/检测与防护等（非具体漏洞也可）
- ignore：与安全无关（招聘、课程、抽奖、泛技术新闻等）

提示：英文关键词例如 vulnerability/exploit/patch/advisory/CVE/zero-day/RCE/XSS/SSRF/SQLi/auth bypass/privilege escalation/malware/ransomware/phishing/APT/IOC/supply chain/data breach。

输出严格 JSON：{{"kind":"vuln|security|ignore","reason":"<=20字"}}

标题：{title}
"""
    out = _chat_completions(
        ai,
        [{"role": "user", "content": prompt}],
        max_tokens=120,
    ).strip()
    try:
        obj = json.loads(_extract_json_candidate(out))
        kind = str(obj.get("kind", "ignore")).strip()
        reason = str(obj.get("reason", "")).strip()
        if kind not in ("vuln", "security", "ignore"):
            kind = "ignore"
        return AIClassified(kind=kind, short_reason=reason[:50])
    except Exception:
        return AIClassified(kind="security", short_reason="fallback")


def aggregate_today(ai: AIConfig, *, items_vuln: list[str], items_sec: list[str]) -> AIAggregation:
    def _fmt(xs: list[str]) -> str:
        return "\n".join([f"- {t}" for t in xs])

    if not items_vuln and not items_sec:
        return AIAggregation(vuln_intel="", security_posture="")

    prompt = f"""你是一名资深安全专家助手。以下是从 RSS 获取、经 AI 筛选后缓存到本地的“今日累计安全资讯”（仅标题，可能包含中文/英文/混合）。

请输出严格 JSON（不要输出其它文字）：
{{
  "vuln_intel": "今日漏洞（情报）…",
  "security_posture": "今日安全态势总结…"
}}

写作要求：
- 重点关注：**安全漏洞、投毒/供应链污染、风险提示、已在野利用/安全事件**
- 需要覆盖中文与英文标题中涉及的安全信息；对英文标题用中文总结即可
- 两段都用中文要点列表（每段 4-10 条要点，简洁、可执行）
- **硬性要求**：你写出的每一条要点，都必须能在下方原始资讯列表里找到对应“标题”（要点里需引用对应标题的原文片段或完整标题）
- 不要编造任何不在列表中的事件/CVE/公告/受影响版本

常见线索（中英文都要识别）：CVE/0day/zero-day/exploit/PoC/advisory/patch/RCE/提权/绕过/XSS/SSRF/SQLi/供应链/投毒/ransomware/勒索/phishing/钓鱼/APT/IOC/data breach/数据泄露。

【漏洞相关】
{_fmt(items_vuln[:80])}

【安全相关】
{_fmt(items_sec[:120])}
"""
    out = _chat_completions(ai, [{"role": "user", "content": prompt}], max_tokens=1100).strip()
    if not out:
        return AIAggregation(vuln_intel="", security_posture="")
    try:
        obj = json.loads(_extract_json_candidate(out))
        vuln_intel = str((obj or {}).get("vuln_intel", "")).strip()
        security_posture = str((obj or {}).get("security_posture", "")).strip()
        return AIAggregation(vuln_intel=vuln_intel, security_posture=security_posture)
    except Exception:
        # JSON 解析失败：降级为纯文本（仍然要求与原始列表一致，靠 prompt 约束）
        log.warning("AI aggregate json parse failed, fallback to plain text")
        txt = out.strip()
        # 尝试用常见标题切分
        vuln_intel = ""
        security_posture = ""
        if "vuln_intel" in txt or "security_posture" in txt:
            # 避免把半截 JSON 当正文
            return AIAggregation(vuln_intel="", security_posture="")
        if "今日漏洞" in txt and "态势" in txt:
            security_posture = txt
        else:
            # 默认把整段放在态势总结里
            security_posture = txt
        return AIAggregation(vuln_intel=vuln_intel, security_posture=security_posture)

