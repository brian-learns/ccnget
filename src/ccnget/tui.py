"""Textual TUI for ccnget — browse the CC-NEWS index and read archived articles.

``ccnget tui`` opens a terminal UI with three panes:

* **Browse** — walk the SURT host tree one level at a time.
* **Scan** — wildcard capture search by SURT prefix.
* **Reader** — fetch a capture (from a scan row, or a plain URL) and render
  it as an article: metadata block + markdown body.

Requires the optional ``tui`` extra: ``pip install ccnget[tui]``.

Architecture: blocking work (CDX queries, WARC retrieve, extraction) runs in
Textual workers (threads) which post messages back to the app; all widget
updates happen on the main thread.
"""

from __future__ import annotations

import argparse
from typing import Any, ClassVar, override

import requests
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from ccnget.api import (
    CDX_URL,
    CcngetError,
    LookupEntry,
    NoRecordError,
    NotFoundError,
    SurtBrowseResult,
    SurtScanResult,
)
from ccnget.api import (
    extent as api_extent,
)
from ccnget.api import (
    retrieve as api_retrieve,
)
from ccnget.api import (
    surt_browse as api_surt_browse,
)
from ccnget.api import (
    surt_prefix as api_surt_prefix,
)
from ccnget.article import ArticleResult, extract
from ccnget.config import _resolve

# ── Formatting helpers ────────────────────────────────────────────────────


def surt_to_host(surt: str) -> str:
    """The host part of a SURT key: ``com,aa,news)/x`` -> ``news.aa.com``."""
    host_part = surt.split(")", 1)[0]
    labels = host_part.split(",")
    return ".".join(reversed(labels))


def surt_to_url(surt: str) -> str:
    """Best-effort original URL from a SURT key (the WARC record header is
    authoritative and used by the Reader once a capture is retrieved)."""
    host_part, _, path = surt.partition(")")
    labels = host_part.split(",")
    host = ".".join(reversed(labels))
    return f"https://{host}/{path.lstrip('/')}"


def fmt_ts(ts: str) -> str:
    """Format a CDX timestamp ``YYYYMMDDhhmmss`` as ``YYYY-MM-DD HH:MM:SS``."""
    if not ts or len(ts) < 14:
        return ts or "—"
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"


def fmt_bytes(n: Any) -> str:
    """Format a byte count for display."""
    if n is None:
        return "—"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n < 1024:
        return f"{n} B"
    if n < 1048576:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1048576:.2f} MB"


def fmt_num(n: Any) -> str:
    """Format an integer with thousands separators."""
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _meta_lines(res: ArticleResult) -> list[str]:
    """Metadata block for the Reader (YAML-ish, one field per line)."""
    lines = [f"url: {res.metadata.get('url', res.url)}"]
    for key in ("title", "author", "date", "language", "hostname", "sitename", "description"):
        value = res.metadata.get(key)
        if value:
            lines.append(f"{key}: {value}")
    lines.extend(
        [
            f"fallback_level: {res.fallback_level}",
            f"timestamp: {fmt_ts(res.timestamp)}",
            f"warc_path: {res.warc_path}",
        ]
    )
    return lines


# ── Messages posted from workers (handled on the main thread) ──
# Defined at module level: handler names derive from the class __qualname__
# (on_boot_loaded, on_browse_loaded, ...) so they must stay unqualified.


class BootLoaded(Message):
    """Extent stats + resolved base URL, ready for the header."""

    def __init__(self, file_extent: int, span: str, total: str, base: str) -> None:
        super().__init__()
        self.file_extent = file_extent
        self.span = span
        self.total = total
        self.base = base


class BootFailed(Message):
    """The CDX server could not be reached at startup."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class BrowseLoaded(Message):
    """Children for the current browse pattern, ready to render."""

    def __init__(self, result: SurtBrowseResult) -> None:
        super().__init__()
        self.result = result


class BrowseError(Message):
    """A browse query failed."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class ScanLoaded(Message):
    """Scan results, ready to render."""

    def __init__(self, result: SurtScanResult) -> None:
        super().__init__()
        self.result = result


class ScanError(Message):
    """A prefix scan failed."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class ArticleLoaded(Message):
    """An extracted article, ready to render in the Reader."""

    def __init__(self, result: ArticleResult) -> None:
        super().__init__()
        self.result = result


class ArticleError(Message):
    """A fetch/extract failed; *message* is user-facing."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


# ── App ───────────────────────────────────────────────────────────────────


class CcngetTUI(App[None]):
    """Textual app: SURT tree browse + prefix scan + article reader."""

    TITLE = "ccnget — CC-NEWS"
    CSS = """
    Header { dock: top; }
    Footer { dock: bottom; }
    #main-tabs { height: 1fr; }
    .pane { height: 1fr; }
    .row { height: auto; width: 100%; padding: 0 1; }
    .bc { color: $primary; }
    .meta { height: auto; width: 100%; padding: 0 1; color: $text; }
    #reader-body { height: 1fr; }
    #reader-body Markdown { height: 1fr; padding: 0 1; }
    .status { color: $text-muted; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("1", "switch_tab('browse')", "Browse"),
        Binding("2", "switch_tab('scan')", "Scan"),
        Binding("3", "switch_tab('reader')", "Reader"),
    ]

    def __init__(self, cdx_url: str | None = None) -> None:
        super().__init__()
        self.cdx_url: str | None = cdx_url
        # Browse state
        self.browse_pattern: str = ""
        self.browse_offset: int = 0
        self.browse_limit: int = 50
        self.browse_children: list[str] = []
        self.browse_total_children: int = 0
        # Scan state
        self.scan_entries: list[LookupEntry] = []
        # Reader state
        self.reader_result: ArticleResult | None = None
        self._exit_code: int = 0

    # ── compose ──

    @override
    def compose(self) -> ComposeResult:
        """Build the three-pane layout (Browse, Scan, Reader) with header/footer."""
        yield Header()
        with Vertical(id="main"):
            with TabbedContent(initial="browse", id="main-tabs"):
                with TabPane("Browse", id="browse"):
                    with Vertical(classes="pane"):
                        yield Label("", id="bc-label", classes="bc row")
                        yield Label("", id="bc-pattern", classes="row")
                        with Horizontal(classes="row", id="browse-controls"):
                            yield Select.from_values([10, 25, 50, 100, 200], value=50, id="browse-limit")
                            yield Button("reload", variant="primary", id="browse-reload")
                        yield DataTable(cursor_type="row", id="browse-table")
                        with Horizontal(classes="row", id="browse-pager"):
                            yield Button("first", id="b-first")
                            yield Button("prev", id="b-prev")
                            yield Label("", id="b-label", classes="status")
                            yield Button("next", id="b-next")
                            yield Button("last", id="b-last")
                        yield Label("", id="browse-status", classes="status row")
                with TabPane("Scan", id="scan"):
                    with Vertical(classes="pane"):
                        with Horizontal(classes="row", id="scan-controls"):
                            yield Input(placeholder="SURT prefix, e.g. com,reuters", id="scan-input")
                            yield Button("scan", variant="primary", id="scan-go")
                            yield Select.from_values([5, 10, 25, 50, 100], value=25, id="scan-limit")
                        yield DataTable(cursor_type="row", id="scan-table")
                        yield Label("", id="scan-status", classes="status row")
                with TabPane("Reader", id="reader"):
                    with Vertical(classes="pane"):
                        with Horizontal(classes="row", id="reader-controls"):
                            yield Input(placeholder="URL to fetch from the archive", id="reader-url")
                            yield Button("fetch", variant="primary", id="reader-fetch")
                        yield Static("", id="reader-meta", classes="meta")
                        with VerticalScroll(id="reader-body"):
                            yield Markdown("", id="reader-markdown")
                        yield Label("", id="reader-status", classes="status row")
        yield Footer()

    # ── startup ──

    def on_mount(self) -> None:
        """Kick off the boot worker (extent + header + root browse)."""
        self._boot()

    @work(thread=True, exclusive=True, group="boot")
    def _boot(self) -> None:
        """Query extent (and total capture count) off the main thread."""
        try:
            ext = api_extent(cdx_url=self.cdx_url)
        except Exception as exc:
            self.post_message(BootFailed(str(exc)))
            return
        try:
            base = _resolve("cdx-url", default=CDX_URL, env_var="CDX_URL")
        except Exception:  # pragma: no cover
            base = CDX_URL
        span = f"{ext.file_oldest[19:26]} → {ext.file_newest[19:26]}"
        try:
            root = api_surt_browse("", limit=1, cdx_url=self.cdx_url)
            total = f"{fmt_num(root.total_entries)} captures  ·  "
        except Exception:  # pragma: no cover - non-fatal, browse load reports it
            total = ""
        self.post_message(BootLoaded(ext.file_extent, span, total, base))

    def on_boot_loaded(self, event: BootLoaded) -> None:
        """Render the header stats and load the root browse level."""
        self.query_one("#bc-label", Label).update(
            Text.assemble(
                ("cdx-rocks", "bold"),
                (
                    f"  {fmt_num(event.file_extent)} WARC files  ·  {event.span}  ·  {event.total}{event.base}",
                    "dim",
                ),
            )
        )
        self._load_browse()

    def on_boot_failed(self, event: BootFailed) -> None:
        """Exit with code 5 when the server is unreachable."""
        self._exit_code = 5
        self.notify(f"CDX server unreachable: {event.message}", severity="error")
        self.exit()

    # ── Browse ──

    def _load_browse(self) -> None:
        """Reset the browse pane and launch the browse query worker."""
        self.query_one("#browse-table", DataTable).clear(columns=True)
        self._set_status("#browse-status", f"querying {self.browse_pattern or 'root'} …")
        self._browse_query()

    @work(thread=True, exclusive=True, group="browse")
    def _browse_query(self) -> None:
        """Query the SURT tree off the main thread."""
        try:
            r = api_surt_browse(
                self.browse_pattern,
                limit=self.browse_limit,
                offset=self.browse_offset,
                cdx_url=self.cdx_url,
            )
        except (CcngetError, requests.RequestException) as exc:
            self.post_message(BrowseError(str(exc)))
            return
        self.post_message(BrowseLoaded(r))

    def on_browse_loaded(self, event: BrowseLoaded) -> None:
        """Render a browse result: breadcrumb, children table, and pager."""
        r = event.result
        table = self.query_one("#browse-table", DataTable)
        table.clear(columns=True)
        table.add_column("surt pattern")
        table.add_column("host")
        table.add_column("captures")
        table.add_column("")
        children = list(r.children.items())
        self.browse_children = [k for k, _ in children]
        self.browse_total_children = r.total_children
        max_count = max((c for _, c in children), default=0)
        for key, count in children:
            share = (count / max_count) if max_count else 0
            bar_cell = Text.assemble(
                (fmt_num(count), ""),
                ("  ", "dim"),
                (self._bar(share), "rgb(88,166,255) on rgb(33,38,45)"),
            )
            table.add_row(key, surt_to_host(key), bar_cell, Text("captures →"), key=key)

        # breadcrumb (crumbs rendered next to the stats)
        labels = r.pattern.split(",") if r.pattern else []
        crumbs = " / ".join(["root", *labels])
        self.query_one("#bc-pattern", Label).update(
            Text.assemble(("path: ", "dim"), (crumbs, "bold"), ("   enter = drill in", "dim"))
        )

        # pager
        limit = r.limit or 1
        pages = max(1, -(-r.total_children // limit))
        page = (r.offset // limit) + 1
        self.query_one("#b-label", Label).update(f"page {page} of {pages} · {fmt_num(r.total_children)} children")
        self.query_one("#b-first", Button).disabled = r.offset == 0
        self.query_one("#b-prev", Button).disabled = r.offset == 0
        self.query_one("#b-next", Button).disabled = r.next_offset is None
        self.query_one("#b-last", Button).disabled = r.next_offset is None
        self._set_status("#browse-status", "")
        table.focus()

    def on_browse_error(self, event: BrowseError) -> None:
        """Show a browse query error in the status line."""
        self._set_status("#browse-status", f"error: {event.message}")

    @staticmethod
    def _bar(share: float) -> str:
        """A tiny ASCII proportion bar (12 cells)."""
        width = 12
        filled = round(share * width)
        filled = max(0, min(width, filled))
        return "█" * filled + "░" * (width - filled)

    # ── Browse interactions ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Drill into a browse row, or fetch a scan row into the Reader."""
        if event.data_table.id == "browse-table":
            pattern = self.browse_children[event.cursor_row]
            self.browse_pattern = pattern
            self.browse_offset = 0
            self._load_browse()
        elif event.data_table.id == "scan-table":
            entry = self.scan_entries[event.cursor_row]
            self._fetch_entry(entry)

    def _select_int(self, select_id: str) -> int:
        """Read a Select's current value as an int (options are ints)."""
        raw = self.query_one(f"#{select_id}", Select).value
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw)
            except ValueError:  # pragma: no cover
                return 10
        return 10

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle pager, reload, scan, and fetch buttons."""
        if event.button.id == "browse-reload":
            self._load_browse()
        elif event.button.id == "b-first":
            self.browse_offset = 0
            self._load_browse()
        elif event.button.id == "b-prev":
            self.browse_offset = max(0, self.browse_offset - self.browse_limit)
            self._load_browse()
        elif event.button.id == "b-next":
            self.browse_offset += self.browse_limit
            self._load_browse()
        elif event.button.id == "b-last":
            pages = max(1, -(-self.browse_total_children // max(1, self.browse_limit)))
            self.browse_offset = (pages - 1) * self.browse_limit
            self._load_browse()
        elif event.button.id == "scan-go":
            self._run_scan()
        elif event.button.id == "reader-fetch":
            self._fetch_url(self.query_one("#reader-url", Input).value)

    def on_select_changed(self, event: Select.Changed) -> None:
        """React to limit dropdown changes (re-query the affected pane)."""
        if event.select.id == "browse-limit":
            self.browse_limit = self._select_int("browse-limit")
            self.browse_offset = 0
            self._load_browse()
        elif event.select.id == "scan-limit":
            if self.query_one("#scan-input", Input).value:
                self._run_scan()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Focus each pane's natural entry widget when it becomes visible."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active == "browse":
            self.query_one("#browse-table", DataTable).focus()
        elif tabs.active == "scan":
            table = self.query_one("#scan-table", DataTable)
            if table.row_count:
                table.focus()
            else:
                self.query_one("#scan-input", Input).focus()
        elif tabs.active == "reader":
            # Focus the markdown body (scrollable, consumes no printable
            # keys) rather than the URL input — an empty focused input would
            # swallow the `q` quit key.
            self.query_one("#reader-markdown", Markdown).focus()

    def on_key(self, event: events.Key) -> None:
        """Global key handling for keys inputs would otherwise swallow.

        * `q` quits — unless an input is focused and has content (typing `q`
          into a URL should not quit the app). An *empty* focused input still
          quits, so `q` is never a dead key.
        * `escape` leaves a focused input (blur to the app) so the tab
          bindings (1/2/3) and table navigation work again.
        """
        if event.key == "escape" and isinstance(self.focused, Input):
            self.focused.blur()
            return
        if event.key != "q":
            return
        focused = self.focused
        if isinstance(focused, Input) and focused.value:
            return
        event.stop()
        self.exit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Run a scan or fetch when an input is submitted with Enter."""
        if event.input.id == "scan-input":
            self._run_scan()
        elif event.input.id == "reader-url":
            self._fetch_url(event.input.value)

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a tab by id (browse/scan/reader)."""
        self.query_one("#main-tabs", TabbedContent).active = tab_id

    # ── Scan ──

    def _run_scan(self) -> None:
        """Validate and launch a prefix scan for the current input."""
        prefix = self.query_one("#scan-input", Input).value.strip()
        if not prefix:
            self._set_status("#scan-status", "enter a SURT prefix first")
            return
        self.query_one("#scan-table", DataTable).clear(columns=True)
        self._set_status("#scan-status", f"scanning {prefix} …")
        self._scan(prefix, self._select_int("scan-limit"))

    @work(thread=True, exclusive=True, group="scan")
    def _scan(self, prefix: str, limit: int) -> None:
        """Query the prefix endpoint off the main thread."""
        try:
            r = api_surt_prefix(prefix, limit=limit, cdx_url=self.cdx_url)
        except (CcngetError, requests.RequestException) as exc:
            self.post_message(ScanError(str(exc)))
            return
        self.post_message(ScanLoaded(r))

    def on_scan_loaded(self, event: ScanLoaded) -> None:
        """Render scan results; rows carry the data needed to fetch a capture."""
        r = event.result
        table = self.query_one("#scan-table", DataTable)
        table.clear(columns=True)
        table.add_column("url (from surt)")
        table.add_column("timestamp")
        table.add_column("size")
        self.scan_entries = list(r.results)
        for e in r.results:
            table.add_row(
                surt_to_url(e.surt_key), fmt_ts(e.timestamp), fmt_bytes(e.length), key=e.surt_key + e.timestamp
            )
        self._set_status(
            "#scan-status",
            f"{r.total_results} captures returned for {r.surt_prefix} "
            f"(top-{r.limit}, not a true total) — enter fetches into the Reader",
        )
        if self.scan_entries:
            table.focus()

    def on_scan_error(self, event: ScanError) -> None:
        """Show a scan error in the status line."""
        self._set_status("#scan-status", f"error: {event.message}")

    # ── Reader ──

    def _fetch_entry(self, entry: LookupEntry) -> None:
        """Retrieve one specific capture by WARC location and render it."""
        self.action_switch_tab("reader")
        url = surt_to_url(entry.surt_key)
        self.query_one("#reader-url", Input).value = url
        self._set_status("#reader-status", f"fetching {fmt_ts(entry.timestamp)} capture …")
        self.query_one("#reader-meta", Static).update("fetching …")
        self.query_one("#reader-markdown", Markdown).update("")
        self._fetch_capture(entry, url)

    @work(thread=True, exclusive=True, group="reader")
    def _fetch_capture(self, entry: LookupEntry, url: str) -> None:
        """Retrieve + extract off the main thread (the slow part)."""
        try:
            fr = api_retrieve(
                entry.warc_path,
                entry.offset,
                entry.length,
                surt_key=entry.surt_key,
                timestamp=entry.timestamp,
            )
        except NoRecordError as exc:
            self.post_message(ArticleError(f"no response record: {exc}"))
            return
        except requests.RequestException as exc:
            self.post_message(ArticleError(f"request failed: {exc}"))
            return
        res = extract(
            fr.payload,
            url=url,
            timestamp=fr.timestamp,
            warc_path=fr.warc_path,
            surt_key=fr.surt_key,
            http_headers=fr.http_headers,
            warc_headers=fr.warc_headers,
        )
        self.post_message(ArticleLoaded(res))

    def _fetch_url(self, url: str) -> None:
        """Fetch a URL (first archived capture) and render it in the Reader."""
        url = url.strip()
        if not url:
            self._set_status("#reader-status", "enter a URL first")
            return
        self.action_switch_tab("reader")
        self.query_one("#reader-url", Input).value = url
        self._set_status("#reader-status", f"looking up {url} …")
        self.query_one("#reader-meta", Static).update("fetching …")
        self.query_one("#reader-markdown", Markdown).update("")
        self._fetch_url_work(url)

    @work(thread=True, exclusive=True, group="reader")
    def _fetch_url_work(self, url: str) -> None:
        """Resolve a URL to its first archived capture off the main thread."""
        try:
            from ccnget.article import article as article_fn

            res = article_fn(url, cdx_url=self.cdx_url)
        except NotFoundError:
            self.post_message(ArticleError(f"no match for {url}"))
            return
        except (CcngetError, requests.RequestException) as exc:
            self.post_message(ArticleError(str(exc)))
            return
        self.post_message(ArticleLoaded(res))

    def on_article_loaded(self, event: ArticleLoaded) -> None:
        """Show the metadata block and markdown body for an article."""
        res = event.result
        if res.fallback_level == 0:
            self.query_one("#reader-meta", Static).update(Text("\n".join(_meta_lines(res))))
            self._set_status("#reader-status", f"no extractable text ({len(res.payload)} bytes)")
            return
        self._render_article(res)

    def on_article_error(self, event: ArticleError) -> None:
        """Show a fetch/extract error in the Reader."""
        self.query_one("#reader-meta", Static).update("error")
        self._set_status("#reader-status", event.message)

    def _render_article(self, res: ArticleResult) -> None:
        """Update the Reader widgets for a fully extracted article."""
        self.reader_result = res
        self.query_one("#reader-meta", Static).update(Text("\n".join(_meta_lines(res))))
        body = res.body or "_(no extractable text)_"
        self.query_one("#reader-markdown", Markdown).update(body)
        self._set_status("#reader-status", f"fallback level {res.fallback_level} · {len(res.payload)} bytes payload")

    # ── helpers ──

    def _set_status(self, selector: str, text: str) -> None:
        """Update a status line label by selector."""
        self.query_one(selector, Label).update(text)


def _tui_main(argv: list[str] | None = None) -> int:
    """Entry point for ``ccnget tui``; returns a process exit code."""
    parser = argparse.ArgumentParser(prog="ccnget tui", description="Textual TUI for the CC-NEWS index")
    parser.add_argument(
        "--cdx-url", default=None, help="CDX server base URL override (default: config > env > built-in)"
    )
    args = parser.parse_args(argv)
    app = CcngetTUI(cdx_url=args.cdx_url)
    app.run()
    return app._exit_code
