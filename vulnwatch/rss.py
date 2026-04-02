from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import feedparser
import requests
from xml.etree import ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import time

log = logging.getLogger("vulnwatch.rss")


@dataclass(frozen=True)
class RssItem:
    source: str
    title: str
    url: str
    published_at: Optional[str]  # ISO8601 if available


def _to_iso(entry: dict) -> Optional[str]:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    try:
        dt = datetime(*st[:6], tzinfo=timezone.utc).replace(microsecond=0)
        return dt.isoformat()
    except Exception:
        return None


def _is_http_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _load_text(
    source: str,
    *,
    timeout_s: int,
    retries: int = 3,
    retry_backoff_s: float = 1.5,
) -> Optional[str]:
    if _is_http_url(source):
        attempts = max(1, int(retries))
        backoff = float(retry_backoff_s)
        last_err: str | None = None
        for i in range(1, attempts + 1):
            try:
                r = requests.get(
                    source,
                    headers={"User-Agent": "vulnwatch/0.1"},
                    timeout=(5, timeout_s),
                )
                if r.status_code >= 400:
                    last_err = f"http={r.status_code}"
                    log.info("opml/http fail %s attempt=%s/%s url=%s", last_err, i, attempts, source)
                else:
                    return r.text
            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e}"
                log.info("opml/http error attempt=%s/%s url=%s err=%s", i, attempts, source, last_err)
            if i < attempts:
                time.sleep(backoff * i)
        log.info("opml/http giveup url=%s last_err=%s", source, last_err or "unknown")
        return None
    try:
        return Path(source).read_text(encoding="utf-8")
    except Exception:
        log.info("opml/file read error path=%s", source)
        return None


def expand_opml_sources(
    sources: Iterable[str],
    *,
    timeout_s: int = 25,
    retries: int = 3,
    retry_backoff_s: float = 1.5,
) -> list[str]:
    """
    sources 支持：
    - RSS URL
    - OPML 文件路径（*.opml）
    - OPML URL（http(s)://.../*.opml）
    """
    out: list[str] = []
    for s in sources:
        s = (s or "").strip()
        if not s:
            continue
        if s.lower().endswith(".opml"):
            txt = _load_text(
                s,
                timeout_s=timeout_s,
                retries=retries,
                retry_backoff_s=retry_backoff_s,
            )
            if not txt:
                log.info("opml empty/unreadable source=%s", s)
                continue
            try:
                root = ET.fromstring(txt)
            except Exception:
                log.info("opml parse error source=%s", s)
                continue
            found = 0
            for el in root.iter():
                xml_url = el.attrib.get("xmlUrl") or el.attrib.get("xmlurl")
                if xml_url and str(xml_url).strip():
                    out.append(str(xml_url).strip())
                    found += 1
            log.info("opml expanded source=%s feeds=%s", s, found)
        else:
            out.append(s)
    # 去重保持顺序
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    return uniq


def fetch_rss(
    urls: Iterable[str],
    *,
    timeout_s: int = 25,
    max_feeds: int | None = None,
    max_workers: int = 24,
) -> list[RssItem]:
    url_list: list[str] = []
    for u in urls:
        u = (u or "").strip()
        if u:
            url_list.append(u)
        if max_feeds is not None and int(max_feeds) > 0 and len(url_list) >= int(max_feeds):
            break

    def _fetch_one(u: str) -> list[RssItem]:
        try:
            r = requests.get(
                u,
                headers={"User-Agent": "vulnwatch/0.1"},
                timeout=(5, timeout_s),
            )
            if r.status_code >= 400:
                log.info("feed fail http=%s url=%s", r.status_code, u)
                raise requests.RequestException(f"http={r.status_code}")
            parsed = feedparser.parse(r.content)
        except requests.RequestException:
            log.info("feed error url=%s", u)
            return []
        feed_title = (parsed.feed.get("title") or u).strip()
        out: list[RssItem] = []
        for e in parsed.entries or []:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or e.get("id") or "").strip()
            if not title or not link:
                continue
            out.append(
                RssItem(
                    source=feed_title,
                    title=title,
                    url=link,
                    published_at=_to_iso(e),
                )
            )
        log.info("feed ok url=%s items=%s", u, len(out))
        return out

    items: list[RssItem] = []
    if not url_list:
        return items
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_fetch_one, u) for u in url_list]
        for fut in as_completed(futs):
            try:
                items.extend(fut.result())
            except Exception:
                continue
    return items


def parse_published_dt(it: RssItem) -> Optional[datetime]:
    if not it.published_at:
        return None
    s = it.published_at.strip()
    # feedparser 的时间我们写的是 UTC ISO；这里只做最简单的解析
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except Exception:
        return None

