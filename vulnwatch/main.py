from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import AppConfig, load_config
from .logging_utils import setup_logging
from .opml_sync import list_local_opml_files, update_opml_to_dir
from .render import build_archive_markdown, build_today_markdown, resolve_paths
from .rss import RssItem, expand_opml_sources, fetch_rss, parse_published_dt
from .storage import init_db, list_news_items_for_day, upsert_news_item

log = logging.getLogger("vulnwatch")


def _match_keywords(title: str, include: list[str], exclude: list[str]) -> bool:
    t = title.lower()
    for x in exclude:
        if x and x.lower() in t:
            return False
    if not include:
        return True
    return any(x.lower() in t for x in include if x)


def _dedup_items(items: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for source, title, url in items:
        u = (url or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(((source or "").strip(), (title or "").strip(), u))
    out.sort(key=lambda x: (x[0].lower(), x[1].lower(), x[2]))
    return out


def run_once(conf: AppConfig, *, update_opml: bool = False, rss_dir: Path | None = None) -> Path:
    init_db(conf.db_path)
    today = date.today()
    today_path, today_archive_path = resolve_paths(conf.content_dir, today)
    # Keep archive history; only compute "today full list" by day column.
    acc_sec0, acc_vuln0 = list_news_items_for_day(conf.db_path, today)
    seen_today: set[str] = {u for _s, _t, u in (acc_sec0 + acc_vuln0) if u}

    rss_dir = (rss_dir or Path("rss")).resolve()
    if update_opml:
        # -u：先把 config 里的 OPML URL 更新到本地 rss/ 目录
        update_opml_to_dir(
            conf.rss,
            out_dir=rss_dir,
            timeout_s=int(conf.opml_timeout_s),
            retries=int(conf.opml_retries),
            backoff_s=float(conf.opml_retry_backoff_s),
        )

    # 不指定 -u：只读取本地 rss/*.opml；指定 -u：更新后也仍读取本地 rss/*.opml
    local_opml = list_local_opml_files(rss_dir)
    if not local_opml:
        log.warning("no local opml found in %s", rss_dir.as_posix())

    # OPML 展开：从本地 OPML 读取 xmlUrl，并保留 outline 的 title/text 作为订阅源展示名
    rss_feeds = expand_opml_sources(
        local_opml,
        timeout_s=int(conf.opml_timeout_s),
        retries=int(conf.opml_retries),
        retry_backoff_s=float(conf.opml_retry_backoff_s),
    )
    log.info("expanded feeds=%s", len(rss_feeds))
    if not rss_feeds:
        log.warning("no feeds expanded (check OPML url/path and timeout)")
    items = fetch_rss(
        rss_feeds,
        timeout_s=conf.rss_timeout_s,
    )
    log.info("fetched items=%s", len(items))
    now_local = datetime.now().astimezone()
    window_start = now_local - timedelta(hours=int(conf.fetch_within_hours))
    # 先做关键词粗筛 + 去重
    uniq: dict[str, RssItem] = {}
    for it in items:
        dt = parse_published_dt(it)
        # 只获取“当前时间往前 N 小时”窗口内的资讯（按本地时区比较）
        if dt is None:
            continue
        dlocal = dt.astimezone(now_local.tzinfo)
        if dlocal < window_start or dlocal > now_local:
            continue
        # today.md 要全量“今天”的，所以这里只把“今天发布”的入库
        if dlocal.date() != today:
            continue
        if not _match_keywords(it.title, conf.keywords_include, conf.keywords_exclude):
            continue
        if it.url in uniq:
            continue
        if it.url in seen_today:
            continue
        uniq[it.url] = it
        if len(uniq) >= conf.max_items_per_run:
            break
    log.info(
        "candidates=%s window_hours=%s now=%s tz=%s",
        len(uniq),
        int(conf.fetch_within_hours),
        now_local.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S"),
        now_local.tzinfo,
    )

    n_upserted = 0
    for it in uniq.values():
        upsert_news_item(
            conf.db_path,
            day=today,
            kind="security",
            source=it.source,
            title=it.title,
            url=it.url,
            published_at=it.published_at,
        )
        n_upserted += 1
    log.info("upserted=%s", n_upserted)

    # 从 DB 读取“今天全量”渲染（不是本次运行抓到的子集）
    acc_sec, acc_vuln = list_news_items_for_day(conf.db_path, today)
    today_items = _dedup_items(acc_sec + acc_vuln)

    today_path.parent.mkdir(parents=True, exist_ok=True)
    today_archive_path.parent.mkdir(parents=True, exist_ok=True)
    today_body = build_today_markdown(d=today, raw_items=today_items)
    today_path.write_text(today_body, encoding="utf-8")
    today_archive_body = build_archive_markdown(d=today, raw_items=today_items)
    today_archive_path.write_text(today_archive_body, encoding="utf-8")

    return today_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vulnwatch", description="Hourly RSS → keywords/window filter → today.md + archive")
    ap.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    ap.add_argument("-u", "--update-opml", action="store_true", help="Update remote OPML into local rss/ then read local OPML")
    ap.add_argument("--rss-dir", default="rss", help="Local OPML directory (default: rss)")
    args = ap.parse_args(argv)

    conf = load_config(args.config)
    setup_logging(conf.log.level)
    out = run_once(conf, update_opml=bool(args.update_opml), rss_dir=Path(str(args.rss_dir)))
    print(out.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

