import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import report  # noqa: E402


def test_render_groups_and_orders_by_severity():
    out = report.render(
        [
            report.DeviceReport("a", report.OK, "fine"),
            report.DeviceReport("b", report.MANUAL, "ssh dead"),
            report.DeviceReport("c", report.FIXED, "relaunched"),
            report.DeviceReport("d", report.SKIPPED, "one-off"),
        ],
        now=datetime(2026, 5, 25, 10, 0, 0),
    )
    lines = out.splitlines()
    assert lines[0].startswith("io.net worker check @ 2026-05-25T10:00:00")
    # MANUAL must be reported before OK so it cannot get lost in scrollback
    assert lines.index("[MANUAL] (1)") < lines.index("[OK] (1)")
    assert "  - b: ssh dead" in lines


def test_render_omits_empty_buckets():
    out = report.render([report.DeviceReport("a", report.OK, "fine")])
    assert "MANUAL" not in out
    assert "FIXED" not in out


def test_markdown_append_creates_with_header(tmp_path):
    p = tmp_path / "reports.md"
    body = report.render_markdown(
        [report.DeviceReport("a", report.OK, "fine"),
         report.DeviceReport("b", report.MANUAL, "ssh dead")],
        now=datetime(2026, 5, 25, 10, 0, 0),
    )
    report.append_markdown(p, body)
    text = p.read_text()
    assert text.startswith("# io.net Worker Reports")
    assert "## 2026-05-25T10:00:00" in text
    # OK entries are summarised, not listed
    assert "ok=1" in text and "manual=1" in text
    assert "**MANUAL** `b`" in text
    assert "`a`" not in text


def test_markdown_append_does_not_duplicate_header(tmp_path):
    p = tmp_path / "reports.md"
    for hour in (10, 11):
        body = report.render_markdown(
            [report.DeviceReport("a", report.FIXED, "relaunched")],
            now=datetime(2026, 5, 25, hour, 0, 0),
        )
        report.append_markdown(p, body)
    text = p.read_text()
    assert text.count("# io.net Worker Reports") == 1
    assert text.count("## 2026-05-25T") == 2


def test_render_markdown_strips_ansi_from_detail():
    body = report.render_markdown(
        [report.DeviceReport("a", report.MANUAL, "\x1b[31mError:\x1b[0m bad")],
        now=datetime(2026, 5, 25, 10, 0, 0),
    )
    assert "\x1b" not in body
    assert "Error: bad" in body
