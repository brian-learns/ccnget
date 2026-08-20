"""Tests for ccnget.article (extraction) and the fetch subcommand output modes."""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock, patch

import pytest

from ccnget.api import FetchResult
from ccnget.article import (
    ArticleResult,
    _dedupe_paragraphs,
    _format_timestamp,
    _get_first_paragraph,
    _split_frontmatter,
    _strip_html_tags,
    _title_from_url,
    _yaml_meta,
    article,
    article_to_dict,
    article_to_text,
)
from ccnget.output import EXIT_API

# ── fixtures ──────────────────────────────────────────────────────────────

SAMPLE_HTML = (
    "<html><head><title>Test Article</title>"
    "<meta property='og:site_name' content='Example News'></head>"
    "<body><h1>Test Article</h1>"
    "<p>First paragraph with enough text to pass the minimum length threshold check.</p>"
    "<p>Second paragraph with more text so the article has a couple of sections.</p>"
    "</body></html>"
)


def _make_warc_response(payload: bytes) -> bytes:
    """Create a minimal WARC record with the given payload."""
    from io import BytesIO

    from warcio.warcwriter import WARCWriter

    buf = BytesIO()
    writer = WARCWriter(buf, gzip=True)
    http_response = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + payload
    record = writer.create_warc_record("http://example.com", "response", payload=BytesIO(http_response))
    writer.write_record(record)
    return buf.getvalue()


def _fetch_result(payload: bytes = SAMPLE_HTML.encode()) -> FetchResult:
    return FetchResult(
        payload=payload,
        http_headers={"Content-Type": "text/html"},
        warc_headers={},
        surt_key="com,example)/",
        timestamp="20170101000000",
        warc_path="crawl-data/test.warc.gz",
    )


# ── pure helpers ──────────────────────────────────────────────────────────


class TestHelpers:
    def test_format_timestamp(self):
        assert _format_timestamp("20170101000000") == "2017-01-01"

    def test_format_timestamp_short(self):
        assert _format_timestamp("2017") == "2017"

    def test_format_timestamp_empty(self):
        assert _format_timestamp("") == ""

    def test_strip_html_tags(self):
        text = _strip_html_tags("<p>Hello &amp; world</p><script>x</script>")
        assert "Hello & world" in text
        assert "<" not in text

    def test_split_frontmatter(self):
        text = "---\ntitle: X\n---\nbody here"
        assert _split_frontmatter(text) == "body here"

    def test_split_frontmatter_no_frontmatter(self):
        assert _split_frontmatter("plain text") == "plain text"

    def test_get_first_paragraph(self):
        text = "# Title\n\nIntro paragraph that is long enough to be picked up.\n\nSecond paragraph.\n"
        para = _get_first_paragraph(text)
        assert para.startswith("Intro paragraph")
        assert "Second paragraph" not in para

    def test_dedupe_paragraphs(self):
        text = "para one\n\npara one\n\npara two"
        assert _dedupe_paragraphs(text) == "para one\n\npara two"

    def test_title_from_url(self):
        assert _title_from_url("http://example.com/news/my-cool-article.html") == "My Cool Article"

    def test_title_from_url_no_path(self):
        assert _title_from_url("http://example.com/") == ""

    def test_yaml_meta(self):
        block = _yaml_meta({"url": "http://x", "categories": ["a", "b"]})
        assert block.startswith("---\n")
        assert block.endswith("\n---")
        assert "categories: [a, b]" in block

    def test_yaml_meta_fields_filter(self):
        block = _yaml_meta({"url": "http://x", "title": "T"}, fields=["url"])
        assert "title" not in block
        assert "url: http://x" in block


# ── article() extraction ──────────────────────────────────────────────────


class TestArticle:
    @patch("ccnget.article.api_fetch")
    def test_level1_extraction(self, mock_fetch):
        mock_fetch.return_value = _fetch_result()
        res = article("http://example.com")
        assert res.fallback_level == 1
        assert res.url == "http://example.com"
        assert res.surt_key == "com,example)/"
        assert res.warc_path == "crawl-data/test.warc.gz"
        assert res.metadata["url"] == "http://example.com"
        assert res.metadata["date"] == "2017-01-01"
        assert res.body  # markdown body extracted
        assert len(res.payload) > 0

    @patch("ccnget.article._extract_level_1", return_value=None)
    @patch("ccnget.article._extract_level_2", return_value="A decent amount of text for level two extraction to keep.")
    def test_level2_extraction(self, mock_l2, mock_l1):
        mock_fetch = patch("ccnget.article.api_fetch", return_value=_fetch_result(b"whatever"))
        with mock_fetch:
            res = article("http://example.com/story-2.html")
        assert res.fallback_level == 2
        assert res.metadata["title"] == "Story 2"
        assert "level two extraction" in res.body

    @patch("ccnget.article._extract_level_1", return_value=None)
    @patch("ccnget.article._extract_level_2", return_value=None)
    @patch("ccnget.article._extract_level_3", return_value="raw stripped text that is long enough to count.")
    def test_level3_extraction(self, mock_l3, mock_l2, mock_l1):
        mock_fetch = patch("ccnget.article.api_fetch", return_value=_fetch_result(b"raw bytes"))
        with mock_fetch:
            res = article("http://example.com/story-3.html")
        assert res.fallback_level == 3
        assert res.metadata["title"] == "Story 3"
        assert "raw stripped text" in res.body

    @patch("ccnget.article._extract_level_1", return_value=None)
    @patch("ccnget.article._extract_level_2", return_value=None)
    @patch("ccnget.article._extract_level_3", return_value=None)
    def test_no_extraction(self, mock_l3, mock_l2, mock_l1):
        mock_fetch = patch("ccnget.article.api_fetch", return_value=_fetch_result(b"\x00\x01\x02"))
        with mock_fetch:
            res = article("http://example.com")
        assert res.fallback_level == 0
        assert res.body == ""
        assert res.payload == b"\x00\x01\x02"


# ── dict / text views ─────────────────────────────────────────────────────


def _sample_article() -> ArticleResult:
    return ArticleResult(
        url="http://example.com",
        payload=b"raw",
        http_headers={},
        warc_headers={},
        surt_key="com,example)/",
        timestamp="20170101000000",
        warc_path="test.warc.gz",
        metadata={"url": "http://example.com", "title": "T", "date": "2017-01-01"},
        body="First paragraph that is long enough to survive the brief filter.\n\nSecond paragraph.",
        fallback_level=1,
    )


class TestViews:
    def test_dict_shape(self):
        d = article_to_dict(_sample_article())
        assert set(d) == {"url", "surt_key", "timestamp", "warc_path", "fallback_level", "metadata", "body"}
        assert d["metadata"]["title"] == "T"
        assert "First paragraph" in d["body"]

    def test_dict_brief(self):
        d = article_to_dict(_sample_article(), mode="brief")
        assert "Second paragraph" not in d["body"]
        assert "First paragraph" in d["body"]

    def test_text_full(self):
        text = article_to_text(_sample_article())
        assert text.startswith("---\n")
        assert "title: T" in text
        assert "Second paragraph." in text

    def test_text_brief(self):
        text = article_to_text(_sample_article(), mode="brief")
        assert "Second paragraph" not in text

    def test_text_quiet(self):
        text = article_to_text(_sample_article(), quiet=True)
        assert "Second paragraph" not in text
        assert "title: T" in text


# ── fetch CLI output modes ────────────────────────────────────────────────


class TestFetchCli:
    def _mock(self, mock_get, payload: bytes = SAMPLE_HTML.encode()):
        lookup_response = MagicMock()
        lookup_response.json.return_value = {
            "results": [
                {
                    "surt_key": "com,example)/",
                    "timestamp": "20170101000000",
                    "warc_path": "test.warc.gz",
                    "offset": 100,
                    "length": 50,
                }
            ]
        }
        retrieve_response = MagicMock()
        retrieve_response.content = _make_warc_response(payload)
        mock_get.side_effect = [lookup_response, retrieve_response]

    @patch("ccnget.api.requests.get")
    def test_default_is_article_text(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com"])
        out = capsys.readouterr().out
        assert out.startswith("---\n")
        assert "url: http://example.com" in out
        # markdown body, not raw HTML
        assert "<html>" not in out
        assert "<p>" not in out

    @patch("ccnget.api.requests.get")
    def test_json(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["url"] == "http://example.com"
        assert data["fallback_level"] in (1, 2, 3)
        assert data["surt_key"] == "com,example)/"
        assert "body" in data
        assert "metadata" in data

    @patch("ccnget.api.requests.get")
    def test_compact_single_line(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--compact"])
        out = capsys.readouterr().out
        assert len(out.strip().splitlines()) == 1
        assert json.loads(out)["url"] == "http://example.com"

    @patch("ccnget.api.requests.get")
    def test_select_metadata_field(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--select", "metadata.url"])
        assert capsys.readouterr().out.strip() == "http://example.com"

    @patch("ccnget.api.requests.get")
    def test_select_metadata_object(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--select", "metadata"])
        data = json.loads(capsys.readouterr().out)
        assert data["url"] == "http://example.com"

    @patch("ccnget.api.requests.get")
    def test_select_body(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--select", "body"])
        out = capsys.readouterr().out.strip()
        assert out  # non-empty markdown body, no frontmatter
        assert not out.startswith("---")

    @patch("ccnget.api.requests.get")
    def test_quiet_metadata_only(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--json", "--quiet"])
        data = json.loads(capsys.readouterr().out)
        assert "body" not in data
        assert "metadata" in data

    @patch("ccnget.api.requests.get")
    def test_quiet_text(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--quiet"])
        out = capsys.readouterr().out
        assert out.startswith("---\n")
        # frontmatter only: no body after closing fence
        assert out.count("---") == 2

    @patch("ccnget.api.requests.get")
    def test_mode_brief(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--mode", "brief", "--select", "body"])
        out = capsys.readouterr().out.strip()
        assert "Second paragraph" not in out

    @patch("ccnget.api.requests.get")
    def test_raw_writes_bytes(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get)
        main(["fetch", "http://example.com", "--raw"])
        out = capsys.readouterr().out
        assert "<html>" in out

    @patch("ccnget.api.requests.get")
    def test_raw_to_file(self, mock_get, tmp_path):
        from ccnget.geturl import main

        self._mock(mock_get)
        out_file = tmp_path / "page.html"
        main(["fetch", "http://example.com", "--raw", "-o", str(out_file)])
        assert out_file.exists()
        assert b"<html>" in out_file.read_bytes()

    @patch("ccnget.api.requests.get")
    def test_article_to_file(self, mock_get, capsys, tmp_path):
        from ccnget.geturl import main

        self._mock(mock_get)
        out_file = tmp_path / "article.md"
        main(["fetch", "http://example.com", "-o", str(out_file)])
        assert out_file.exists()
        text = out_file.read_text()
        assert text.startswith("---\n")
        assert capsys.readouterr().out == ""  # nothing on stdout

    @patch("ccnget.api.requests.get")
    def test_api_error_exit_code(self, mock_get):
        import requests

        from ccnget.geturl import main

        mock_get.side_effect = requests.exceptions.ConnectionError("boom")
        with pytest.raises(SystemExit) as exc_info:
            main(["fetch", "http://example.com", "--json"])
        assert exc_info.value.code == EXIT_API

    @patch("ccnget.api.requests.get")
    def test_no_extractable_text_exit_code(self, mock_get, capsys):
        from ccnget.geturl import main

        self._mock(mock_get, payload=b"\x00\x01\x02\x03")
        with pytest.raises(SystemExit) as exc_info:
            main(["fetch", "http://example.com"])
        assert exc_info.value.code == EXIT_API
        assert "no extractable text" in capsys.readouterr().err

    def test_parser_flags(self):
        from ccnget.geturl import get_parser

        parser = get_parser()
        args = parser.parse_args(
            ["fetch", "http://x", "--mode", "brief", "--quiet", "--raw", "--json", "--select", "body"]
        )
        assert args.mode == "brief"
        assert args.quiet is True
        assert args.raw is True
        assert args.json_flag is True
        assert args.select == "body"
        assert not hasattr(args, "table_flag")  # fetch has no --table

    def test_parser_rejects_table_flag(self):
        from ccnget.geturl import get_parser

        parser = get_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["fetch", "http://x", "--table"])
