"""Per-check report rendering and persistent markdown log."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

OK = "ok"
FIXED = "fixed"
MANUAL = "manual"
SKIPPED = "skipped"
ORDER = (MANUAL, FIXED, SKIPPED, OK)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class DeviceReport:
    name: str
    status: str
    detail: str = ""


def render(reports: list[DeviceReport], *, now: datetime | None = None) -> str:
    now = now or datetime.now()
    lines = [f"io.net worker check @ {now.isoformat(timespec='seconds')}"]
    buckets: dict[str, list[DeviceReport]] = {}
    for r in reports:
        buckets.setdefault(r.status, []).append(r)
    for status in ORDER:
        items = buckets.get(status)
        if not items:
            continue
        lines.append(f"[{status.upper()}] ({len(items)})")
        for r in items:
            lines.append(f"  - {r.name}: {r.detail}" if r.detail else f"  - {r.name}")
    return "\n".join(lines)


def render_markdown(reports: list[DeviceReport], *, now: datetime | None = None) -> str:
    """Compact markdown for the persistent log: only entries needing attention
    plus a one-line summary."""
    now = now or datetime.now()
    counts = {OK: 0, FIXED: 0, MANUAL: 0, SKIPPED: 0}
    for r in reports:
        counts[r.status] = counts.get(r.status, 0) + 1

    lines = [
        f"## {now.isoformat(timespec='seconds')}",
        "",
        f"Summary: ok={counts[OK]} fixed={counts[FIXED]} "
        f"manual={counts[MANUAL]} skipped={counts[SKIPPED]} "
        f"total={len(reports)}",
    ]

    # Only spell out the entries that matter — MANUAL and FIXED.
    interesting = [r for r in reports if r.status in (MANUAL, FIXED, SKIPPED)]
    if interesting:
        lines.append("")
        for r in interesting:
            # Collapse multi-line launcher output so it doesn't break the bullet.
            detail = " ".join(ANSI_RE.sub("", r.detail).split())
            if len(detail) > 240:
                detail = detail[:237] + "..."
            lines.append(f"- **{r.status.upper()}** `{r.name}` — {detail}")
    lines.append("")
    return "\n".join(lines)


def append_markdown(path: Path, body: str) -> None:
    """Append a markdown block. Creates the file with a top-level header if new."""
    if not path.exists():
        header = "# io.net Worker Reports\n\n"
        path.write_text(header + body)
        return
    existing = path.read_text()
    sep = "" if existing.endswith("\n") else "\n"
    path.write_text(existing + sep + body)
