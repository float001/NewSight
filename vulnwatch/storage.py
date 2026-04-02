from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SeenItem:
    url: str
    first_seen_at: str
    last_seen_at: str
    seen_date: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_items (
              url TEXT PRIMARY KEY,
              first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              seen_date TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_date ON seen_items(seen_date)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_items (
              url TEXT PRIMARY KEY,
              day TEXT NOT NULL,
              kind TEXT NOT NULL,
              source TEXT NOT NULL,
              title TEXT NOT NULL,
              published_at TEXT,
              first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_day ON news_items(day)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_kind ON news_items(kind)")


def was_seen(db_path: Path, url: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT url FROM seen_items WHERE url = ? LIMIT 1", (url,)).fetchone()
        return row is not None


def mark_seen(db_path: Path, url: str, *, seen_date: date | None = None) -> None:
    d = (seen_date or date.today()).isoformat()
    now = _utc_now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO seen_items(url, first_seen_at, last_seen_at, seen_date)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              last_seen_at = excluded.last_seen_at,
              seen_date = excluded.seen_date
            """,
            (url, now, now, d),
        )


def list_seen_urls_for_date(db_path: Path, d: date) -> set[str]:
    ds = d.isoformat()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT url FROM seen_items WHERE seen_date = ?", (ds,)).fetchall()
    return {r[0] for r in rows if r and r[0]}


def upsert_news_item(
    db_path: Path,
    *,
    day: date,
    kind: str,
    source: str,
    title: str,
    url: str,
    published_at: str | None = None,
) -> None:
    now = _utc_now_iso()
    ds = day.isoformat()
    k = kind if kind in ("security", "vuln") else "security"
    sql = """
        INSERT INTO news_items(url, day, kind, source, title, published_at, first_seen_at, last_seen_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
          day = excluded.day,
          kind = excluded.kind,
          source = excluded.source,
          title = excluded.title,
          published_at = COALESCE(excluded.published_at, news_items.published_at),
          last_seen_at = excluded.last_seen_at
        """
    args = (url, ds, k, source, title, published_at, now, now)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(sql, args)
    except sqlite3.OperationalError as e:
        # 自愈：某些情况下 db 文件存在但 schema 未初始化
        if "no such table" in str(e):
            init_db(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.execute(sql, args)
            return
        raise


def list_news_items_for_day(db_path: Path, day: date) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """
    Return (security_items, vuln_items) each as [(source,title,url)] sorted by source/title.
    """
    ds = day.isoformat()
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT kind, source, title, url FROM news_items WHERE day = ?",
                (ds,),
            ).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            init_db(db_path)
            return ([], [])
        raise
    sec: list[tuple[str, str, str]] = []
    vuln: list[tuple[str, str, str]] = []
    for kind, source, title, url in rows or []:
        rec = (source or "", title or "", url or "")
        if kind == "vuln":
            vuln.append(rec)
        else:
            sec.append(rec)
    sec.sort(key=lambda x: (x[0].lower(), x[1].lower(), x[2]))
    vuln.sort(key=lambda x: (x[0].lower(), x[1].lower(), x[2]))
    return sec, vuln


def prune_to_day(db_path: Path, day: date) -> None:
    """
    Keep only rows for the given day. This enforces "today only" semantics.
    """
    ds = day.isoformat()
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM seen_items WHERE seen_date <> ?", (ds,))
        conn.execute("DELETE FROM news_items WHERE day <> ?", (ds,))

