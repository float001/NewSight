from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from .logging_utils import LogConfig


@dataclass(frozen=True)
class AIConfig:
    enabled: bool
    base_url: str
    api_key_env: str
    api_key: str
    model: str
    timeout_s: int = 45

    @property
    def resolved_api_key(self) -> str:
        return os.getenv(self.api_key_env, "") or self.api_key


@dataclass(frozen=True)
class LarkConfig:
    enabled: bool
    webhook_env: str
    webhook: str

    @property
    def resolved_webhook(self) -> str:
        return os.getenv(self.webhook_env, "") or self.webhook


@dataclass(frozen=True)
class AppConfig:
    rss: list[str]
    keywords_include: list[str]
    keywords_exclude: list[str]
    fetch_within_hours: int
    rss_timeout_s: int
    opml_timeout_s: int
    opml_retries: int
    opml_retry_backoff_s: float
    log: LogConfig
    ai: AIConfig
    lark: LarkConfig
    content_dir: Path
    db_path: Path
    max_items_per_run: int = 200


def _as_list(x: Any) -> list[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i) for i in x if str(i).strip()]
    return [str(x)]


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    rss = _as_list(raw.get("rss"))
    rss_cfg = raw.get("rss_config") or {}
    kw = raw.get("keywords") or {}
    include = _as_list(kw.get("include"))
    exclude = _as_list(kw.get("exclude"))
    fetch_within_hours = int(kw.get("fetch_within_hours", raw.get("fetch_within_hours", 1)))
    if fetch_within_hours <= 0:
        fetch_within_hours = 1

    rss_timeout_s = int(rss_cfg.get("timeout_s", 12))
    if rss_timeout_s <= 0:
        rss_timeout_s = 12
    opml_timeout_s = int(rss_cfg.get("opml_timeout_s", 60))
    if opml_timeout_s <= 0:
        opml_timeout_s = 60
    opml_retries = int(rss_cfg.get("opml_retries", 3))
    if opml_retries < 1:
        opml_retries = 1
    if opml_retries > 10:
        opml_retries = 10
    opml_retry_backoff_s = float(rss_cfg.get("opml_retry_backoff_s", 1.5))
    if opml_retry_backoff_s <= 0:
        opml_retry_backoff_s = 1.5

    log_raw = raw.get("log") or {}
    log = LogConfig(level=str(log_raw.get("level", "INFO")))

    ai_raw = raw.get("ai") or {}
    ai = AIConfig(
        enabled=bool(ai_raw.get("enabled", True)),
        base_url=str(ai_raw.get("base_url", "https://api.openai.com/v1")).rstrip("/"),
        api_key_env=str(ai_raw.get("api_key_env", "OPENAI_API_KEY")),
        api_key=str(ai_raw.get("api_key", "")),
        model=str(ai_raw.get("model", "gpt-4o-mini")),
        timeout_s=int(ai_raw.get("timeout_s", 45)),
    )

    lark_raw = raw.get("lark") or {}
    lark = LarkConfig(
        enabled=bool(lark_raw.get("enabled", False)),
        webhook_env=str(lark_raw.get("webhook_env", "LARK_WEBHOOK")),
        webhook=str(lark_raw.get("webhook", "")),
    )

    content_dir = Path(str(raw.get("content_dir", "content"))).resolve()
    db_path = Path(str(raw.get("db_path", "state/state.db"))).resolve()

    return AppConfig(
        rss=rss,
        keywords_include=include,
        keywords_exclude=exclude,
        fetch_within_hours=fetch_within_hours,
        rss_timeout_s=rss_timeout_s,
        opml_timeout_s=opml_timeout_s,
        opml_retries=opml_retries,
        opml_retry_backoff_s=opml_retry_backoff_s,
        log=log,
        ai=ai,
        lark=lark,
        content_dir=content_dir,
        db_path=db_path,
        max_items_per_run=int(raw.get("max_items_per_run", 200)),
    )

