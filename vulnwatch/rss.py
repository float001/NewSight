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
) -> list[tuple[str, str]]:
    """
    展开 config 中的 RSS / OPML，返回 (feed_xml_url, opml_outline_title)。

    OPML 中每个带 xmlUrl 的 outline 会取其 ``title`` 或 ``text`` 作为第二项；
    非 OPML 的直接 RSS 地址第二项为空字符串，拉取后仍用 RSS feed 自带标题作 source。
    """
    out: list[tuple[str, str]] = []
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
                if not xml_url or not str(xml_url).strip():
                    continue
                xml_url = str(xml_url).strip()
                label = (el.attrib.get("title") or el.attrib.get("text") or "").strip()
                out.append((xml_url, label))
                found += 1
            log.info("opml expanded source=%s feeds=%s", s, found)
        else:
            out.append((s, ""))
    # 去重保持顺序（同一 xmlUrl 只保留首次出现的 OPML 标题）
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for u, lab in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((u, lab))
    return uniq


def fetch_rss(
    feeds: Iterable[tuple[str, str]],
    *,
    timeout_s: int = 25,
    max_feeds: int | None = None,
    max_workers: int = 24,
) -> list[RssItem]:
    """
    feeds: (feed_xml_url, opml_outline_title_or_empty)。
    若第二项非空，则作为 ``RssItem.source``（与 Markdown 里按源分组名称一致）；否则用 RSS feed 自带 title。
    """
    feed_list: list[tuple[str, str]] = []
    for u, opml_title in feeds:
        u = (u or "").strip()
        if not u:
            continue
        feed_list.append((u, (opml_title or "").strip()))
        if max_feeds is not None and int(max_feeds) > 0 and len(feed_list) >= int(max_feeds):
            break

    def _fetch_one(u: str, opml_title: str) -> list[RssItem]:
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
        feed_title = (opml_title or (parsed.feed.get("title") or u) or "").strip()
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
        log.info("feed ok url=%s items=%s source=%s", u, len(out), feed_title[:80])
        return out

    items: list[RssItem] = []
    if not feed_list:
        return items
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_fetch_one, u, ot) for u, ot in feed_list]
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

