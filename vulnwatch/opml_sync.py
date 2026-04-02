from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger("vulnwatch.opml")


def _safe_name_from_url(url: str) -> str:
    p = urlparse(url)
    base = (Path(p.path).name or "feeds.opml").strip()
    if not base.lower().endswith(".opml"):
        base = base + ".opml"
    return base


def update_opml_to_dir(
    sources: list[str],
    *,
    out_dir: Path,
    timeout_s: int = 90,
    retries: int = 3,
    backoff_s: float = 1.5,
) -> list[Path]:
    """
    将 config 里的 OPML URL 列表下载到本地 rss/ 目录。
    只处理 http(s) URL；本地路径会被忽略（本地 OPML 直接放 rss/ 即可）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for url in sources:
        url = (url or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        name = _safe_name_from_url(url)
        target = out_dir / name
        last_err: str | None = None
        for i in range(1, max(1, int(retries)) + 1):
            try:
                r = requests.get(url, timeout=(5, timeout_s))
                if r.status_code >= 400:
                    last_err = f"http={r.status_code}"
                    log.info("opml update fail %s attempt=%s url=%s", last_err, i, url)
                else:
                    target.write_bytes(r.content)
                    saved.append(target)
                    log.info("opml updated file=%s bytes=%s", target.as_posix(), len(r.content))
                    last_err = None
                    break
            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e}"
                log.info("opml update error attempt=%s url=%s err=%s", i, url, last_err)
            if i < int(retries):
                import time

                time.sleep(float(backoff_s) * i)
        if last_err:
            log.warning("opml update giveup url=%s last_err=%s", url, last_err)
    return saved


def list_local_opml_files(rss_dir: Path) -> list[str]:
    if not rss_dir.is_dir():
        return []
    return [p.as_posix() for p in sorted(rss_dir.glob("*.opml")) if p.is_file()]

