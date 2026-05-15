#!/usr/bin/env python3
"""Regenerate issues/INDEX.md by scanning local issues/*.md files.

Use this after creating or editing an issue file. Reads YAML frontmatter
from each OPT-N.md and groups by status. No external dependencies; safe
to run any time.
"""

import re
from datetime import datetime
from pathlib import Path

ISSUES_DIR = Path(__file__).resolve().parent.parent / "issues"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

STATUS_ORDER = [
    "Triage", "Backlog", "In Progress", "In Review",
    "Done", "Canceled", "Duplicate",
]


def parse_frontmatter(text):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm


def opt_number(ident):
    try:
        return int(ident.split("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def main():
    issues = []
    for path in ISSUES_DIR.glob("OPT-*.md"):
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm.get("id"):
            continue
        issues.append({
            "id": fm["id"],
            "title": fm.get("title", "(untitled)"),
            "status": fm.get("status", "Backlog"),
        })

    by_status = {}
    for i in issues:
        by_status.setdefault(i["status"], []).append(i)

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        "# OptionLedger Issue Archive",
        "",
        f"{len(issues)} issues as of {today}.",
        "",
        "## Status summary",
        "",
    ]

    status_order = list(STATUS_ORDER)
    for s in by_status:
        if s not in status_order:
            status_order.append(s)

    for s in status_order:
        if s in by_status:
            lines.append(f"- **{s}**: {len(by_status[s])}")
    lines.append("")

    for s in status_order:
        if s not in by_status:
            continue
        items = sorted(by_status[s], key=lambda i: opt_number(i["id"]), reverse=True)
        lines.append(f"## {s}")
        lines.append("")
        for i in items:
            lines.append(f"- [{i['id']}]({i['id']}.md) — {i['title']}")
        lines.append("")

    (ISSUES_DIR / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {ISSUES_DIR / 'INDEX.md'} with {len(issues)} issues")


if __name__ == "__main__":
    main()
