from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .ai import aggregate_today, classify_titles_batch
from .config import AppConfig, load_config
from .lark import send_lark_card
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


@dataclass
class Selected:
    vuln: list[tuple[str, str, str]]  # source,title,url
    sec: list[tuple[str, str, str]]


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

    # OPML 展开：从本地 OPML 文件读取 xmlUrl
    rss_urls = expand_opml_sources(
        local_opml,
        timeout_s=int(conf.opml_timeout_s),
        retries=int(conf.opml_retries),
        retry_backoff_s=float(conf.opml_retry_backoff_s),
    )
    log.info("expanded feeds=%s", len(rss_urls))
    if not rss_urls:
        log.warning("no feeds expanded (check OPML url/path and timeout)")
    # 避免 OPML 特别大导致单次运行过久：这里对 feed 数量做一个上限
    items = fetch_rss(
        rss_urls,
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

    selected = Selected(vuln=[], sec=[])
    uniq_list = list(uniq.values())
    if conf.ai.enabled and conf.ai.resolved_api_key:
        batch = 28
        for i in range(0, len(uniq_list), batch):
            chunk = uniq_list[i : i + batch]
            flags = classify_titles_batch(conf.ai, [x.title for x in chunk])
            for it, c in zip(chunk, flags, strict=False):
                kind = c.kind
                if kind == "ignore":
                    continue
                # 入库去重：url PRIMARY KEY
                upsert_news_item(
                    conf.db_path,
                    day=today,
                    kind=("vuln" if kind == "vuln" else "security"),
                    source=it.source,
                    title=it.title,
                    url=it.url,
                    published_at=it.published_at,
                )
                if kind == "vuln":
                    selected.vuln.append((it.source, it.title, it.url))
                else:
                    selected.sec.append((it.source, it.title, it.url))
    else:
        # AI 未启用时：把关键词筛选后的都当作 security 原始资讯
        if conf.ai.enabled and not conf.ai.resolved_api_key:
            log.warning("AI enabled but key missing (env=%s), skip classification", conf.ai.api_key_env)
        for it in uniq_list:
            upsert_news_item(
                conf.db_path,
                day=today,
                kind="security",
                source=it.source,
                title=it.title,
                url=it.url,
                published_at=it.published_at,
            )
            selected.sec.append((it.source, it.title, it.url))
    log.info("selected security=%s vuln=%s", len(selected.sec), len(selected.vuln))

    # 从 DB 读取“今天全量”渲染（不是本次运行抓到的子集）
    acc_sec, acc_vuln = list_news_items_for_day(conf.db_path, today)
    today_items = _dedup_items(acc_sec + acc_vuln)

    # Lark 推送：总结仅基于「本次运行」新入库的安全/漏洞子集（与 today 全量解耦）
    run_sec = _dedup_items(selected.sec)
    run_vuln = _dedup_items(selected.vuln)
    agg = aggregate_today(
        conf.ai,
        items_vuln=[t for _s, t, _u in run_vuln],
        items_sec=[t for _s, t, _u in run_sec],
    )
    lark_count = len(run_sec) + len(run_vuln)

    today_path.parent.mkdir(parents=True, exist_ok=True)
    today_archive_path.parent.mkdir(parents=True, exist_ok=True)
    today_body = build_today_markdown(d=today, raw_items=today_items)
    today_path.write_text(today_body, encoding="utf-8")
    today_archive_body = build_archive_markdown(d=today, raw_items=today_items)
    today_archive_path.write_text(today_archive_body, encoding="utf-8")

    # 推送到 Lark：标题与「时间」均为当前本地时间，YYYY-MM-DD HH:mm:ss
    now_lark = datetime.now().astimezone().replace(microsecond=0)
    lark_time_str = now_lark.strftime("%Y-%m-%d %H:%M:%S")
    send_lark_card(
        conf.lark,
        title=f"安全资讯（{lark_time_str}）",
        date_str=lark_time_str,
        count_items=lark_count,
        vuln_intel=agg.vuln_intel,
        security_posture=agg.security_posture,
    )
    return today_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vulnwatch", description="Hourly RSS → AI classify/aggregate → today.md + archive + Lark")
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

