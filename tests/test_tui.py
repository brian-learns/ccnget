"""Tests for the ccnget Textual TUI (src/ccnget/tui.py).

Uses Textual's in-process test harness (App.run_test + Pilot) with the
ccnget.api network functions monkeypatched, so no real server is needed.

Requires the optional ``tui`` extra (``uv sync --extra tui``); the module
skips cleanly when textual is not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual", reason="optional 'tui' extra not installed")

from textual.widgets import DataTable, Input, Label, Markdown, Static, TabbedContent

from ccnget.api import (
    ExtentResult,
    LookupEntry,
    SurtBrowseResult,
    SurtScanResult,
)
from ccnget.tui import (
    CcngetTUI,
    _meta_lines,
    fmt_bytes,
    fmt_num,
    fmt_ts,
    surt_to_host,
    surt_to_url,
)

# ── Fixtures ──────────────────────────────────────────────────────────────

SAMPLE_BROWSE = SurtBrowseResult(
    pattern="",
    count=0,
    total_entries=1_457_993_326,
    children={"com,aa": 5, "com,bb": 3, "net,cc": 1},
    total_children=3,
    offset=0,
    limit=50,
    next_offset=None,
)

SAMPLE_BROWSE_DEEP = SurtBrowseResult(
    pattern="com,aa",
    count=2,
    total_entries=1_457_993_326,
    children={"com,aa,news": 1},
    total_children=1,
    offset=0,
    limit=50,
    next_offset=None,
)

SAMPLE_SCAN = SurtScanResult(
    surt_prefix="com,aa",
    total_results=2,
    limit=25,
    results=[
        LookupEntry(
            surt_key="com,aa,news)/american-stories",
            timestamp="20210401144301",
            warc_path="crawl-data/CC-NEWS/2021/04/a.warc.gz",
            offset=100,
            length=26076,
        ),
        LookupEntry(
            surt_key="com,aaa,ace)/",
            timestamp="20260527143447",
            warc_path="crawl-data/CC-NEWS/2026/05/b.warc.gz",
            offset=863342374,
            length=4658,
        ),
    ],
)

SAMPLE_ARTICLE = {
    "url": "http://www.example.com",
    "surt_key": "com,example)/",
    "timestamp": "20230502155746",
    "warc_path": "crawl-data/CC-NEWS/2023/05/c.warc.gz",
    "fallback_level": 1,
    "metadata": {
        "url": "http://www.example.com",
        "title": "Example Domain",
        "date": "2023-05-02",
        "language": "English",
        "hostname": "www.example.com",
    },
    "body": "# Example Domain\n\nThis domain is for use in illustrative examples.",
}


def _make_article_result(**overrides):
    """Build an ArticleResult from SAMPLE_ARTICLE with optional overrides."""
    from ccnget.article import ArticleResult

    data = {
        "url": SAMPLE_ARTICLE["url"],
        "payload": b"<html>sample</html>",
        "http_headers": {},
        "warc_headers": {"WARC-Target-URI": SAMPLE_ARTICLE["url"]},
        "surt_key": SAMPLE_ARTICLE["surt_key"],
        "timestamp": SAMPLE_ARTICLE["timestamp"],
        "warc_path": SAMPLE_ARTICLE["warc_path"],
        "metadata": dict(SAMPLE_ARTICLE["metadata"]),
        "body": SAMPLE_ARTICLE["body"],
        "fallback_level": SAMPLE_ARTICLE["fallback_level"],
    }
    data.update(overrides)
    return ArticleResult(**data)


def _make_fetch_result():
    from ccnget.api import FetchResult

    return FetchResult(
        payload=b"<html>sample</html>",
        http_headers={},
        warc_headers={"WARC-Target-URI": "http://www.example.com"},
        surt_key="com,example)/",
        timestamp="20230502155746",
        warc_path="crawl-data/CC-NEWS/2023/05/c.warc.gz",
    )


@pytest.fixture
def api_mock(monkeypatch):
    """Patch the ccnget.api network functions used by the TUI."""
    from ccnget import tui as tui_mod

    calls: dict[str, list] = {}

    def _record(name, fn):
        def wrapper(*args, **kwargs):
            calls.setdefault(name, []).append((args, kwargs))
            return fn(*args, **kwargs)

        return wrapper

    def fake_extent(*args, **kwargs):
        return ExtentResult(
            file_extent=51101,
            file_oldest="crawl-data/CC-NEWS/2016/08/CC-NEWS-20160826124520-00000.warc.gz",
            file_newest="crawl-data/CC-NEWS/2026/07/CC-NEWS-20260731214950-00313.warc.gz",
        )

    def fake_browse(pattern, *, limit=50, offset=0, cdx_url=None):
        if pattern == "com,aa":
            return SAMPLE_BROWSE_DEEP
        return SAMPLE_BROWSE

    def fake_prefix(prefix, *, limit=10, cdx_url=None):
        return SurtScanResult(
            surt_prefix=prefix,
            total_results=len(SAMPLE_SCAN.results),
            limit=limit,
            results=list(SAMPLE_SCAN.results),
        )

    def fake_retrieve(warc_path, offset, length, **kwargs):
        return _make_fetch_result()

    def fake_extract(payload, **kwargs):
        return _make_article_result()

    def fake_article(url, **kwargs):
        return _make_article_result()

    monkeypatch.setattr(tui_mod, "api_extent", _record("extent", fake_extent))
    monkeypatch.setattr(tui_mod, "api_surt_browse", _record("browse", fake_browse))
    monkeypatch.setattr(tui_mod, "api_surt_prefix", _record("prefix", fake_prefix))
    monkeypatch.setattr(tui_mod, "api_retrieve", _record("retrieve", fake_retrieve))
    monkeypatch.setattr(tui_mod, "extract", _record("extract", fake_extract))
    monkeypatch.setattr(tui_mod, "api_fetch", _record("fetch", fake_article), raising=False)
    # _fetch_url_work imports article inside the function; patch at the source
    # module (ccnget.article) rather than the package attribute (shadowed by
    # the function of the same name).
    import importlib

    article_mod = importlib.import_module("ccnget.article")
    monkeypatch.setattr(article_mod, "article", fake_article)
    return calls


@pytest.fixture
async def app(api_mock):
    """A running app with mocked API, booted to the root browse level."""
    app = CcngetTUI(cdx_url="http://test.invalid")
    async with app.run_test() as pilot:
        # Wait for boot + root browse to render.
        await pilot.pause(0.2)
        table = app.query_one("#browse-table", DataTable)
        for _ in range(100):
            if table.row_count >= 3:
                break
            await pilot.pause(0.05)
        yield pilot


# ── Formatting helpers ────────────────────────────────────────────────────


class TestFormatting:
    def test_surt_to_host(self):
        assert surt_to_host("com,aa,news)/american-stories") == "news.aa.com"
        assert surt_to_host("com,example)/") == "example.com"

    def test_surt_to_url(self):
        assert surt_to_url("com,aa,news)/american-stories") == "https://news.aa.com/american-stories"
        assert surt_to_url("com,example)/") == "https://example.com/"

    def test_fmt_ts(self):
        assert fmt_ts("20230502155746") == "2023-05-02 15:57:46"
        assert fmt_ts("bogus") == "bogus"
        assert fmt_ts("") == "—"

    def test_fmt_bytes(self):
        assert fmt_bytes(500) == "500 B"
        assert fmt_bytes(2048) == "2.0 KB"
        assert fmt_bytes(3 * 1048576) == "3.00 MB"
        assert fmt_bytes(None) == "—"

    def test_fmt_num(self):
        assert fmt_num(1234567) == "1,234,567"
        assert fmt_num(None) == "—"

    def test_meta_lines(self):
        lines = _meta_lines(_make_article_result())
        text = "\n".join(lines)
        assert "url: http://www.example.com" in text
        assert "title: Example Domain" in text
        assert "fallback_level: 1" in text
        assert "warc_path: crawl-data/CC-NEWS/2023/05/c.warc.gz" in text


# ── App behaviour (harness) ───────────────────────────────────────────────


class TestBoot:
    async def test_boot_renders_extent_and_root(self, app, api_mock):
        pilot = app
        table = pilot.app.query_one("#browse-table", DataTable)
        assert table.row_count == 3
        bc = pilot.app.query_one("#bc-label", Label).render()
        assert "51,101" in str(bc)
        assert "1,457,993,326" in str(bc)

    async def test_boot_unreachable_exits(self, monkeypatch):
        from ccnget import tui as tui_mod

        def boom(*args, **kwargs):
            import requests

            raise requests.ConnectionError("no route to host")

        monkeypatch.setattr(tui_mod, "api_extent", boom)
        app = CcngetTUI(cdx_url="http://test.invalid")
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
        assert app._exit_code == 5


class TestBrowse:
    async def test_root_children_rendered(self, app):
        pilot = app
        table = pilot.app.query_one("#browse-table", DataTable)
        rows = [table.get_cell_at((i, 0)) for i in range(table.row_count)]
        assert rows == ["com,aa", "com,bb", "net,cc"]

    async def test_enter_drills_in(self, app, api_mock):
        pilot = app
        table = pilot.app.query_one("#browse-table", DataTable)
        table.focus()
        table.move_cursor(row=0, column=0)  # com,aa
        await pilot.press("enter")
        for _ in range(100):
            if pilot.app.query_one("#browse-table", DataTable).row_count == 1:
                break
            await pilot.pause(0.05)
        assert pilot.app.browse_pattern == "com,aa"
        rows = [
            pilot.app.query_one("#browse-table", DataTable).get_cell_at((0, 0)),
        ]
        assert rows == ["com,aa,news"]
        # breadcrumb updated
        bc = str(pilot.app.query_one("#bc-pattern", Label).render())
        assert "root" in bc and "com" in bc and "aa" in bc

    async def test_pager_label(self, app):
        pilot = app
        label = pilot.app.query_one("#b-label", Label).render()
        assert "page 1 of 1" in str(label)
        assert "3 children" in str(label)


class TestScan:
    async def test_scan_renders_results(self, app):
        pilot = app
        app2 = pilot.app
        app2.query_one("#scan-input", Input).value = "com,aa"
        app2._run_scan()
        table = app2.query_one("#scan-table", DataTable)
        for _ in range(100):
            if table.row_count >= 2:
                break
            await pilot.pause(0.05)
        assert table.row_count == 2
        url0 = table.get_cell_at((0, 0))
        assert url0 == "https://news.aa.com/american-stories"
        ts0 = table.get_cell_at((0, 1))
        assert ts0 == "2021-04-01 14:43:01"
        size0 = table.get_cell_at((0, 2))
        assert size0 == "25.5 KB"

    async def test_scan_empty_prefix_noop(self, app):
        pilot = app
        app2 = pilot.app
        app2._run_scan()
        await pilot.pause(0.1)
        status = str(app2.query_one("#scan-status", Label).render())
        assert "enter a SURT prefix" in status


class TestReader:
    async def test_scan_enter_fetches_entry(self, app):
        pilot = app
        app2 = pilot.app
        app2.query_one("#scan-input", Input).value = "com,aa"
        app2._run_scan()
        table = app2.query_one("#scan-table", DataTable)
        for _ in range(100):
            if table.row_count >= 2:
                break
            await pilot.pause(0.05)
        table.move_cursor(row=0, column=0)
        table.focus()
        await pilot.press("enter")
        for _ in range(100):
            if app2.reader_result is not None:
                break
            await pilot.pause(0.05)
        assert app2.reader_result is not None
        meta = str(app2.query_one("#reader-meta", Static).render())
        assert "url: http://www.example.com" in meta
        assert "title: Example Domain" in meta
        md = app2.query_one("#reader-markdown", Markdown)
        assert "Example Domain" in md.source

    async def test_reader_url_fetch(self, app):
        pilot = app
        app2 = pilot.app
        app2.query_one("#reader-url", Input).value = "http://example.com/"
        app2._fetch_url("http://example.com/")
        for _ in range(100):
            if app2.reader_result is not None:
                break
            await pilot.pause(0.05)
        assert app2.reader_result is not None
        meta = str(app2.query_one("#reader-meta", Static).render())
        assert "fallback_level: 1" in meta

    async def test_reader_not_found(self, app, monkeypatch):
        import importlib

        from ccnget.api import NotFoundError

        article_mod = importlib.import_module("ccnget.article")

        def nf(url, **kwargs):
            raise NotFoundError(f"no match for {url}")

        monkeypatch.setattr(article_mod, "article", nf)
        pilot = app
        app2 = pilot.app
        app2._fetch_url("http://nope.example/")
        await pilot.pause(0.3)
        status = str(app2.query_one("#reader-status", Label).render())
        assert "no match" in status


class TestTabs:
    async def test_tab_switch_binding(self, app):
        pilot = app
        tabs = pilot.app.query_one("#main-tabs", TabbedContent)
        assert tabs.active == "browse"
        await pilot.press("2")
        await pilot.pause(0.1)
        assert tabs.active == "scan"
        # Switching to Scan auto-focuses the prefix Input, which would swallow
        # the "3" keystroke. Escape blurs it first (real user flow).
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(pilot.app.focused, Input)
        await pilot.press("3")
        await pilot.pause(0.1)
        assert tabs.active == "reader"
