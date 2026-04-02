from __future__ import annotations

from datetime import date, datetime
from pathlib import Path


def _front_matter(d: date, *, is_archive: bool) -> str:
    title = ("安全资讯归档" if is_archive else "今日安全资讯") + f"（{d.isoformat()}）"
    return (
        "---\n"
        f'title: "{title}"\n'
        f"date: {datetime.now().astimezone().replace(microsecond=0).isoformat()}\n"
        "draft: false\n"
        "---\n\n"
    )


def resolve_paths(content_dir: Path, d: date) -> tuple[Path, Path]:
    today_path = content_dir / "today.md"
    archive_path = (
        content_dir
        / "archive"
        / f"{d.year:04d}"
        / f"{d.month:02d}"
        / f"{d.year:04d}-{d.month:02d}-{d.day:02d}.md"
    )
    return today_path, archive_path


def _render_list_block(title: str, items: list[tuple[str, str, str]]) -> str:
    lines: list[str] = []
    if title:
        lines.append(f"## {title}\n\n")
    if not items:
        lines.append("- （今日暂无安全相关资讯）\n\n")
        return "".join(lines)
    by_source: dict[str, list[tuple[str, str]]] = {}
    for source, t, u in items:
        by_source.setdefault(source, []).append((t, u))
    for source, xs in sorted(by_source.items(), key=lambda kv: kv[0].lower()):
        lines.append(f"- {source}\n")
        for t, u in xs:
            lines.append(f"  - [{t}]({u})\n")
    lines.append("\n")
    return "".join(lines)


def parse_rendered_markdown(text: str) -> list[tuple[str, str, str]]:
    """
    Parse lists rendered by _render_list_block.
    Return items as [(source,title,url)].
    """
    out: list[tuple[str, str, str]] = []

    current: list[tuple[str, str, str]] | None = None
    current_source: str | None = None

    for raw in (text or "").splitlines():
        line = raw.rstrip("\n")
        if line.startswith("## "):
            title = line[3:].strip()
            # 兼容：无标题列表时，也允许解析（保持 current 不变）
            if title == "资讯列表":
                current = out
                current_source = None
            continue

        if current is None:
            continue

        if line.startswith("- "):
            s = line[2:].strip()
            if s.startswith("（") and s.endswith("）"):
                current_source = None
            else:
                current_source = s
            continue

        if line.startswith("  - [") and "](" in line and line.endswith(")"):
            if not current_source:
                continue
            try:
                left = line.index("[") + 1
                mid = line.index("](")
                right = line.rindex(")")
                t = line[left:mid]
                u = line[mid + 2 : right]
            except ValueError:
                continue
            t = t.strip()
            u = u.strip()
            if t and u:
                current.append((current_source, t, u))
            continue

    return out


def build_today_markdown(
    *,
    d: date,
    raw_items: list[tuple[str, str, str]],
) -> str:
    """
    today.md 只写入资讯列表（不包含 AI 总结），用于对外展示“原始筛选结果”。
    """
    lines: list[str] = []
    # 不输出 YAML front matter，避免页面渲染时显示配置字段
    lines.append(f"# 今日安全资讯（{d.isoformat()}）\n\n")
    lines.append(_render_list_block("", raw_items))
    return "".join(lines).rstrip() + "\n"


def build_archive_markdown(
    *,
    d: date,
    raw_items: list[tuple[str, str, str]],
) -> str:
    lines: list[str] = []
    # 不输出 YAML front matter，避免页面渲染时显示配置字段
    lines.append(f"# 安全资讯归档（{d.isoformat()}）\n\n")
    lines.append(_render_list_block("", raw_items))
    return "".join(lines).rstrip() + "\n"

