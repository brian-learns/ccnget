import argparse
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from warcio.warcwriter import WARCWriter

from ccnget.api import (
    CcngetError,
    ExtentResult,
    FetchResult,
    LookupEntry,
    LookupResult,
    NoRecordError,
    NotFoundError,
    SurtBrowseResult,
    SurtScanResult,
    _cdx_base,
    _entry_from_dict,
)
from ccnget.api import (
    extent as api_extent,
)
from ccnget.api import (
    fetch as api_fetch,
)
from ccnget.api import (
    lookup as api_lookup,
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
from ccnget.geturl import (
    browse_limit,
    fetch_cmd,
    limited_int,
    lookup_cmd,
    main,
    non_negative_int,
    retrieve_cmd,
    surt_browse_cmd,
    surt_prefix_cmd,
)


def _make_warc_response(payload: bytes) -> bytes:
    """Create a minimal WARC record with the given payload."""
    buf = BytesIO()
    writer = WARCWriter(buf, gzip=True)

    # Create a proper HTTP response as the payload
    http_response = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + payload

    record = writer.create_warc_record(
        "http://example.com",
        "response",
        payload=BytesIO(http_response),
    )
    writer.write_record(record)
    return buf.getvalue()


# ── CLI helpers ────────────────────────────────────────────────────────────


class TestLimitedInt:
    def test_valid_value(self):
        assert limited_int("50") == 50

    def test_min_value(self):
        assert limited_int("1") == 1

    def test_max_value(self):
        assert limited_int("100") == 100

    def test_below_min_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="between 1 and 100"):
            limited_int("0")

    def test_above_max_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="between 1 and 100"):
            limited_int("1001")

    def test_non_integer_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="Must be an integer"):
            limited_int("abc")


# ── CLI parsing tests ─────────────────────────────────────────────────────


class TestMainParsing:
    @patch("ccnget.api.requests.get")
    def test_lookup_subcommand(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        main(["lookup", "http://example.com"])

        captured = capsys.readouterr()
        assert '"results"' in captured.out

    @patch("ccnget.api.requests.get")
    def test_retrieve_subcommand(self, mock_get, capsys):
        warc_content = _make_warc_response(b"test")
        mock_response = MagicMock()
        mock_response.content = warc_content
        mock_get.return_value = mock_response

        main(["retrieve", "--warc-path", "test.warc.gz", "--offset", "0", "--length", "100"])

        captured = capsys.readouterr()
        assert b"test" in captured.out.encode()

    def test_missing_command_fails(self):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_lookup_missing_url_fails(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["lookup"])
        assert exc_info.value.code != 0

    def test_retrieve_missing_required_fails(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["retrieve"])
        assert exc_info.value.code != 0


# ── CLI command tests ─────────────────────────────────────────────────────


class TestLookupCmd:
    @patch("ccnget.api._resolve")
    @patch("ccnget.api.requests.get")
    def test_lookup_calls_api(self, mock_get, mock_resolve):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response
        mock_resolve.return_value = "https://brian-learns-cc-news-cdx-server.hf.space/"

        args = argparse.Namespace(url="http://example.com", exact=False, limit=10, at=None)
        lookup_cmd(args)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "https://brian-learns-cc-news-cdx-server.hf.space/cdx-index/lookup"
        assert call_args[1]["params"]["url"] == "http://example.com"
        assert call_args[1]["params"]["exact"] is False
        assert call_args[1]["params"]["limit"] == 10
        assert call_args[1]["params"]["at"] is None

    @patch("ccnget.api.requests.get")
    def test_lookup_exact_flag(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        args = argparse.Namespace(url="http://example.com", exact=True, limit=5, at=None)
        lookup_cmd(args)

        call_args = mock_get.call_args
        assert call_args[1]["params"]["exact"] is True

    @patch("ccnget.api.requests.get")
    def test_lookup_at_parameter(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        args = argparse.Namespace(url="http://example.com", exact=False, limit=10, at="20240101120000")
        lookup_cmd(args)

        call_args = mock_get.call_args
        assert call_args[1]["params"]["at"] == "20240101120000"


class TestRetrieveCmd:
    @patch("ccnget.api.requests.get")
    def test_retrieve_writes_to_stdout(self, mock_get, capsys):
        warc_content = _make_warc_response(b"<html>test</html>")

        mock_response = MagicMock()
        mock_response.content = warc_content
        mock_get.return_value = mock_response

        args = argparse.Namespace(
            warc_path="test.warc.gz",
            offset=0,
            length=100,
            output=None,
        )
        retrieve_cmd(args)

        captured = capsys.readouterr()
        assert b"<html>test</html>" in captured.out.encode()

    @patch("ccnget.api.requests.get")
    def test_retrieve_writes_to_file(self, mock_get, tmp_path):
        warc_content = _make_warc_response(b"<html>file test</html>")

        mock_response = MagicMock()
        mock_response.content = warc_content
        mock_get.return_value = mock_response

        output_file = tmp_path / "output.html"
        args = argparse.Namespace(
            warc_path="test.warc.gz",
            offset=100,
            length=200,
            output=str(output_file),
        )
        retrieve_cmd(args)

        assert output_file.exists()
        assert output_file.read_bytes() == b"<html>file test</html>"

    @patch("ccnget.api.requests.get")
    def test_retrieve_uses_range_header(self, mock_get):
        warc_content = _make_warc_response(b"test")

        mock_response = MagicMock()
        mock_response.content = warc_content
        mock_get.return_value = mock_response

        args = argparse.Namespace(
            warc_path="path/to/file.warc.gz",
            offset=500,
            length=100,
            output=None,
        )
        retrieve_cmd(args)

        call_args = mock_get.call_args
        expected_url = "https://data.commoncrawl.org/path/to/file.warc.gz"
        assert call_args[0][0] == expected_url
        assert call_args[1]["headers"]["Range"] == "bytes=500-599"


class TestFetchCmd:
    @patch("ccnget.api.requests.get")
    def test_fetch_retrieves_first_result(self, mock_get, capsys):
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

        warc_content = _make_warc_response(b"<html>fetched</html>")
        retrieve_response = MagicMock()
        retrieve_response.content = warc_content

        mock_get.side_effect = [lookup_response, retrieve_response]

        args = argparse.Namespace(url="http://example.com", exact=False, output=None, at=None)
        fetch_cmd(args)

        captured = capsys.readouterr()
        assert b"<html>fetched</html>" in captured.out.encode()
        assert mock_get.call_count == 2

    @patch("ccnget.api.requests.get")
    def test_fetch_with_at_parameter(self, mock_get, capsys):
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

        warc_content = _make_warc_response(b"<html>fetched</html>")
        retrieve_response = MagicMock()
        retrieve_response.content = warc_content

        mock_get.side_effect = [lookup_response, retrieve_response]

        args = argparse.Namespace(url="http://example.com", exact=False, output=None, at="20240101120000")
        fetch_cmd(args)

        call_args = mock_get.call_args_list[0]
        assert call_args[1]["params"]["at"] == "20240101120000"

    @patch("ccnget.api.requests.get")
    def test_fetch_with_output_file(self, mock_get, tmp_path):
        lookup_response = MagicMock()
        lookup_response.json.return_value = {
            "results": [
                {
                    "surt_key": "com,example)/",
                    "timestamp": "20170101000000",
                    "warc_path": "test.warc.gz",
                    "offset": 200,
                    "length": 75,
                }
            ]
        }

        warc_content = _make_warc_response(b"<html>file output</html>")
        retrieve_response = MagicMock()
        retrieve_response.content = warc_content

        mock_get.side_effect = [lookup_response, retrieve_response]

        output_file = tmp_path / "fetched.html"
        args = argparse.Namespace(url="http://example.com", exact=True, output=str(output_file), at=None)
        fetch_cmd(args)

        assert output_file.exists()
        assert output_file.read_bytes() == b"<html>file output</html>"

    @patch("ccnget.api.requests.get")
    def test_fetch_no_results(self, mock_get, capsys):
        lookup_response = MagicMock()
        lookup_response.json.return_value = {"results": []}
        mock_get.return_value = lookup_response

        args = argparse.Namespace(url="http://nonexistent.example", exact=False, output=None, at=None)
        with pytest.raises(SystemExit):
            fetch_cmd(args)

        assert mock_get.call_count == 1
        captured = capsys.readouterr()
        assert "no match for http://nonexistent.example" in captured.err


# ── Library API tests ─────────────────────────────────────────────────────


class TestEntryFromDict:
    def test_basic_entry(self):
        d = {
            "surt_key": "com,example)/",
            "timestamp": "20170101000000",
            "warc_path": "crawl-data/test.warc.gz",
            "offset": 100,
            "length": 500,
        }
        entry = _entry_from_dict(d)
        assert entry.surt_key == "com,example)/"
        assert entry.timestamp == "20170101000000"
        assert entry.warc_path == "crawl-data/test.warc.gz"
        assert entry.offset == 100
        assert entry.length == 500
        assert entry.extra == {}

    def test_extra_fields(self):
        d = {
            "surt_key": "com,example)/",
            "timestamp": "20170101000000",
            "warc_path": "test.warc.gz",
            "offset": 0,
            "length": 100,
            "original_url": "http://example.com",
            "mime_type": "text/html",
        }
        entry = _entry_from_dict(d)
        assert entry.extra["original_url"] == "http://example.com"
        assert entry.extra["mime_type"] == "text/html"


class TestLookup:
    @patch("ccnget.api.requests.get")
    def test_lookup_returns_result(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
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
        mock_get.return_value = mock_response

        result = api_lookup("http://example.com")
        assert isinstance(result, LookupResult)
        assert result.url == "http://example.com"
        assert len(result.entries) == 1
        assert isinstance(result.entries[0], LookupEntry)
        assert result.entries[0].surt_key == "com,example)/"

    @patch("ccnget.api.requests.get")
    def test_lookup_custom_cdx_url(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        api_lookup("http://example.com", cdx_url="http://custom-cdx")
        assert mock_get.call_args[0][0] == "http://custom-cdx/cdx-index/lookup"

    @patch("ccnget.api.requests.get")
    def test_lookup_retry_on_timeout(self, mock_get):
        """Retry is triggered on timeout, returns result on retry."""
        import requests

        # First call raises Timeout, second returns success
        mock_get.side_effect = [
            requests.exceptions.Timeout(),
            MagicMock(json=lambda: {"results": []}),
        ]
        result = api_lookup("http://example.com")
        assert isinstance(result, LookupResult)
        assert mock_get.call_count == 2


class TestCdxBase:
    """Test _cdx_base normalization of cdx-url to a server base URL."""

    def test_trailing_slash(self):
        assert _cdx_base("https://host/") == "https://host"

    def test_lookup_suffix_stripped(self):
        assert _cdx_base("https://host/lookup") == "https://host"

    def test_new_format_endpoint_stripped(self):
        assert _cdx_base("https://host/cdx-index/lookup") == "https://host"

    def test_new_format_endpoint_with_trailing_slash(self):
        assert _cdx_base("http://0.0.0.0:7860/cdx-index/lookup/") == "http://0.0.0.0:7860"

    def test_lookup_suffix_with_trailing_slash(self):
        assert _cdx_base("http://0.0.0.0:8000/lookup/") == "http://0.0.0.0:8000"

    def test_bare_host_unchanged(self):
        assert _cdx_base("http://0.0.0.0:8000") == "http://0.0.0.0:8000"

    def test_default_base(self):
        assert _cdx_base("https://brian-learns-cc-news-cdx-server.hf.space/") == (
            "https://brian-learns-cc-news-cdx-server.hf.space"
        )


class TestRetrieve:
    @patch("ccnget.api.requests.get")
    def test_retrieve_returns_fetch_result(self, mock_get):
        warc_content = _make_warc_response(b"<html>test</html>")
        mock_response = MagicMock()
        mock_response.content = warc_content
        mock_get.return_value = mock_response

        result = api_retrieve("test.warc.gz", 0, 100)
        assert isinstance(result, FetchResult)
        assert result.payload == b"<html>test</html>"
        assert result.warc_path == "test.warc.gz"
        assert isinstance(result.http_headers, dict)
        assert isinstance(result.warc_headers, dict)

    @patch("ccnget.api.requests.get")
    def test_retrieve_custom_base_url(self, mock_get):
        warc_content = _make_warc_response(b"test")
        mock_response = MagicMock()
        mock_response.content = warc_content
        mock_get.return_value = mock_response

        api_retrieve("test.warc.gz", 0, 100, base_url="http://custom-crawl")
        assert mock_get.call_args[0][0] == "http://custom-crawl/test.warc.gz"

    @patch("ccnget.api.requests.get")
    def test_retrieve_accepts_206_partial_content(self, mock_get):
        """S3 returns 206 for Range requests — this should work fine."""
        warc_content = _make_warc_response(b"partial")
        mock_response = MagicMock()
        mock_response.status_code = 206
        mock_response.content = warc_content
        mock_get.return_value = mock_response

        result = api_retrieve("test.warc.gz", 0, 100)
        assert isinstance(result, FetchResult)
        assert result.payload == b"partial"

    @patch("ccnget.api.requests.get")
    def test_retrieve_accepts_200(self, mock_get):
        """200 is also acceptable for range requests (some mirrors)."""
        warc_content = _make_warc_response(b"full")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = warc_content
        mock_get.return_value = mock_response

        result = api_retrieve("test.warc.gz", 0, 100)
        assert isinstance(result, FetchResult)
        assert result.payload == b"full"

    @patch("ccnget.api.requests.get")
    def test_retrieve_rejects_unexpected_status(self, mock_get):
        """Non-200/206 status codes should raise."""
        mock_response = MagicMock()
        mock_response.status_code = 416
        mock_get.return_value = mock_response

        with pytest.raises(RuntimeError, match="Unexpected status 416"):
            api_retrieve("test.warc.gz", 0, 100)

    @patch("ccnget.api.requests.get")
    def test_retrieve_retry_on_connection_error(self, mock_get):
        """Retry is triggered on connection failure."""
        import requests

        warc_content = _make_warc_response(b"retried")
        mock_response = MagicMock()
        mock_response.content = warc_content

        mock_get.side_effect = [
            requests.exceptions.ConnectionError(),
            mock_response,
        ]
        result = api_retrieve("test.warc.gz", 0, 100)
        assert isinstance(result, FetchResult)
        assert mock_get.call_count == 2


class TestFetch:
    @patch("ccnget.api.requests.get")
    def test_fetch_returns_fetch_result(self, mock_get):
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

        warc_content = _make_warc_response(b"<html>fetched</html>")
        retrieve_response = MagicMock()
        retrieve_response.content = warc_content

        mock_get.side_effect = [lookup_response, retrieve_response]

        result = api_fetch("http://example.com")
        assert isinstance(result, FetchResult)
        assert result.payload == b"<html>fetched</html>"
        assert result.surt_key
        assert result.timestamp
        assert mock_get.call_count == 2

    @patch("ccnget.api.requests.get")
    def test_fetch_no_results_raises(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        with pytest.raises(NotFoundError, match="No archived results"):
            api_fetch("http://nonexistent.example")


class TestExtent:
    @patch("ccnget.api._resolve")
    @patch("ccnget.api.requests.get")
    def test_extent_default_base(self, mock_get, mock_resolve):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "file_extent": 14542,
            "file_oldest": "crawl-data/CC-NEWS/2023/01/x.warc.gz",
            "file_newest": "crawl-data/CC-NEWS/2024/12/y.warc.gz",
        }
        mock_get.return_value = mock_response
        mock_resolve.return_value = "https://brian-learns-cc-news-cdx-server.hf.space/"

        result = api_extent()
        assert isinstance(result, ExtentResult)
        assert result.file_extent == 14542
        assert mock_get.call_args[0][0] == (
            "https://brian-learns-cc-news-cdx-server.hf.space/cdx-index/extent"
        )

    @patch("ccnget.api.requests.get")
    def test_extent_custom_cdx_url(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "file_extent": 1,
            "file_oldest": "a.warc.gz",
            "file_newest": "b.warc.gz",
        }
        mock_get.return_value = mock_response

        api_extent(cdx_url="http://custom-cdx/")
        assert mock_get.call_args[0][0] == "http://custom-cdx/cdx-index/extent"

    @patch("ccnget.api.requests.get")
    def test_extent_accepts_legacy_lookup_url(self, mock_get):
        """Old config values ending in /lookup still resolve to the new path."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "file_extent": 1,
            "file_oldest": "a.warc.gz",
            "file_newest": "b.warc.gz",
        }
        mock_get.return_value = mock_response

        api_extent(cdx_url="http://0.0.0.0:8000/lookup")
        assert mock_get.call_args[0][0] == "http://0.0.0.0:8000/cdx-index/extent"


class TestBrowseLimit:
    def test_valid_value(self):
        assert browse_limit("50") == 50

    def test_min_value(self):
        assert browse_limit("1") == 1

    def test_max_value(self):
        assert browse_limit("200") == 200

    def test_below_min_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="between 1 and 200"):
            browse_limit("0")

    def test_above_max_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="between 1 and 200"):
            browse_limit("201")

    def test_non_integer_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="Must be an integer"):
            browse_limit("abc")


class TestNonNegativeInt:
    def test_zero(self):
        assert non_negative_int("0") == 0

    def test_positive(self):
        assert non_negative_int("123") == 123

    def test_negative_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="0 or greater"):
            non_negative_int("-1")

    def test_non_integer_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="Must be an integer"):
            non_negative_int("abc")


class TestSurtBrowse:
    @patch("ccnget.api._resolve")
    @patch("ccnget.api.requests.get")
    def test_default_root_level(self, mock_get, mock_resolve):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "pattern": "",
            "count": 0,
            "total_entries": 1400000000,
            "children": {"com,aa": 900, "com,bb": 800},
            "total_children": 147000,
            "offset": 0,
            "limit": 50,
            "next_offset": 50,
        }
        mock_get.return_value = mock_response
        mock_resolve.return_value = "https://brian-learns-cc-news-cdx-server.hf.space/"

        result = api_surt_browse()
        assert isinstance(result, SurtBrowseResult)
        assert result.pattern == ""
        assert result.count == 0
        assert result.total_entries == 1400000000
        assert result.children == {"com,aa": 900, "com,bb": 800}
        assert result.total_children == 147000
        assert result.offset == 0
        assert result.limit == 50
        assert result.next_offset == 50
        assert mock_get.call_args[0][0] == (
            "https://brian-learns-cc-news-cdx-server.hf.space/cdx-index/surt-browse"
        )
        assert mock_get.call_args[1]["params"] == {"pattern": "", "limit": 50, "offset": 0}

    @patch("ccnget.api.requests.get")
    def test_pattern_limit_offset_passed(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "pattern": "com,aa",
            "count": 900,
            "total_entries": 1400000000,
            "children": {"com,aaa": 700},
            "total_children": 12,
            "offset": 50,
            "limit": 20,
            "next_offset": None,
        }
        mock_get.return_value = mock_response

        result = api_surt_browse("com,aa", limit=20, offset=50)
        assert result.pattern == "com,aa"
        assert result.next_offset is None
        assert mock_get.call_args[1]["params"] == {"pattern": "com,aa", "limit": 20, "offset": 50}

    @patch("ccnget.api.requests.get")
    def test_custom_cdx_url(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "pattern": "",
            "count": 0,
            "total_entries": 1,
            "children": {},
            "total_children": 0,
            "limit": 50,
        }
        mock_get.return_value = mock_response

        api_surt_browse(cdx_url="http://custom-cdx/")
        assert mock_get.call_args[0][0] == "http://custom-cdx/cdx-index/surt-browse"

    @patch("ccnget.api.requests.get")
    def test_accepts_legacy_lookup_url(self, mock_get):
        """Old config values ending in /lookup still resolve to the new path."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "pattern": "",
            "count": 0,
            "total_entries": 1,
            "children": {},
            "total_children": 0,
            "limit": 50,
        }
        mock_get.return_value = mock_response

        api_surt_browse(cdx_url="http://0.0.0.0:8000/lookup")
        assert mock_get.call_args[0][0] == "http://0.0.0.0:8000/cdx-index/surt-browse"

    @patch("ccnget.api.requests.get")
    def test_retry_on_timeout(self, mock_get):
        """Retry is triggered on timeout, returns result on retry."""
        import requests

        mock_get.side_effect = [
            requests.exceptions.Timeout(),
            MagicMock(
                json=lambda: {
                    "pattern": "",
                    "count": 0,
                    "total_entries": 1,
                    "children": {},
                    "total_children": 0,
                    "limit": 50,
                }
            ),
        ]
        result = api_surt_browse()
        assert isinstance(result, SurtBrowseResult)
        assert mock_get.call_count == 2


class TestSurtPrefix:
    @patch("ccnget.api._resolve")
    @patch("ccnget.api.requests.get")
    def test_scan_returns_entries(self, mock_get, mock_resolve):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "surt_prefix": "com,aa",
            "total_results": 2,
            "limit": 10,
            "results": [
                {
                    "surt_key": "com,aaa,ace)/activities",
                    "timestamp": "20170101000000",
                    "warc_path": "test.warc.gz",
                    "offset": 100,
                    "length": 50,
                },
                {
                    "surt_key": "com,aaa,ace)/activities/feed",
                    "timestamp": "20170202000000",
                    "warc_path": "test.warc.gz",
                    "offset": 200,
                    "length": 75,
                },
            ],
        }
        mock_get.return_value = mock_response
        mock_resolve.return_value = "https://brian-learns-cc-news-cdx-server.hf.space/"

        result = api_surt_prefix("com,aa")
        assert isinstance(result, SurtScanResult)
        assert result.surt_prefix == "com,aa"
        assert result.total_results == 2
        assert result.limit == 10
        assert len(result.results) == 2
        assert all(isinstance(e, LookupEntry) for e in result.results)
        assert result.results[0].surt_key == "com,aaa,ace)/activities"
        assert result.results[1].offset == 200
        assert mock_get.call_args[0][0] == (
            "https://brian-learns-cc-news-cdx-server.hf.space/cdx-index/surt-prefix"
        )
        assert mock_get.call_args[1]["params"] == {"prefix": "com,aa", "limit": 10}

    @patch("ccnget.api.requests.get")
    def test_empty_results(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "surt_prefix": "com,nomatch",
            "total_results": 0,
            "limit": 10,
            "results": [],
        }
        mock_get.return_value = mock_response

        result = api_surt_prefix("com,nomatch")
        assert result.total_results == 0
        assert result.results == []

    @patch("ccnget.api.requests.get")
    def test_custom_cdx_url(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "surt_prefix": "com,aa",
            "total_results": 0,
            "limit": 10,
            "results": [],
        }
        mock_get.return_value = mock_response

        api_surt_prefix("com,aa", cdx_url="http://custom-cdx/")
        assert mock_get.call_args[0][0] == "http://custom-cdx/cdx-index/surt-prefix"

    @patch("ccnget.api.requests.get")
    def test_accepts_legacy_lookup_url(self, mock_get):
        """Old config values ending in /lookup still resolve to the new path."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "surt_prefix": "com,aa",
            "total_results": 0,
            "limit": 10,
            "results": [],
        }
        mock_get.return_value = mock_response

        api_surt_prefix("com,aa", cdx_url="http://0.0.0.0:8000/lookup")
        assert mock_get.call_args[0][0] == "http://0.0.0.0:8000/cdx-index/surt-prefix"

    @patch("ccnget.api.requests.get")
    def test_retry_on_timeout(self, mock_get):
        """Retry is triggered on timeout, returns result on retry."""
        import requests

        mock_get.side_effect = [
            requests.exceptions.Timeout(),
            MagicMock(
                json=lambda: {
                    "surt_prefix": "com,aa",
                    "total_results": 0,
                    "limit": 10,
                    "results": [],
                }
            ),
        ]
        result = api_surt_prefix("com,aa")
        assert isinstance(result, SurtScanResult)
        assert mock_get.call_count == 2


class TestSurtBrowseCmd:
    @patch("ccnget.api.requests.get")
    def test_default_root(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "pattern": "",
            "count": 0,
            "total_entries": 1400000000,
            "children": {"com,aa": 900},
            "total_children": 147000,
            "offset": 0,
            "limit": 50,
            "next_offset": None,
        }
        mock_get.return_value = mock_response

        args = argparse.Namespace(pattern="", limit=50, offset=0)
        surt_browse_cmd(args)

        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["children"] == {"com,aa": 900}
        assert out["next_offset"] is None
        assert mock_get.call_args[1]["params"] == {"pattern": "", "limit": 50, "offset": 0}

    @patch("ccnget.api.requests.get")
    def test_pattern_and_pagination(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "pattern": "com,aa",
            "count": 900,
            "total_entries": 1400000000,
            "children": {"com,aaa": 700},
            "total_children": 12,
            "offset": 50,
            "limit": 20,
            "next_offset": 70,
        }
        mock_get.return_value = mock_response

        args = argparse.Namespace(pattern="com,aa", limit=20, offset=50)
        surt_browse_cmd(args)

        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["pattern"] == "com,aa"
        assert mock_get.call_args[1]["params"] == {"pattern": "com,aa", "limit": 20, "offset": 50}

    @patch("ccnget.api.requests.get")
    def test_request_error_exits(self, mock_get, capsys):
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError("boom")
        args = argparse.Namespace(pattern="", limit=50, offset=0)
        with pytest.raises(SystemExit):
            surt_browse_cmd(args)
        assert "boom" in capsys.readouterr().err


class TestSurtPrefixCmd:
    @patch("ccnget.api.requests.get")
    def test_prints_lookup_style_json(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "surt_prefix": "com,aa",
            "total_results": 1,
            "limit": 10,
            "results": [
                {
                    "surt_key": "com,aaa,ace)/activities",
                    "timestamp": "20170101000000",
                    "warc_path": "test.warc.gz",
                    "offset": 100,
                    "length": 50,
                }
            ],
        }
        mock_get.return_value = mock_response

        args = argparse.Namespace(prefix="com,aa", limit=10)
        surt_prefix_cmd(args)

        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["surt_prefix"] == "com,aa"
        assert out["total_results"] == 1
        assert out["results"][0]["surt_key"] == "com,aaa,ace)/activities"
        assert out["results"][0]["warc_path"] == "test.warc.gz"
        assert mock_get.call_args[1]["params"] == {"prefix": "com,aa", "limit": 10}

    @patch("ccnget.api.requests.get")
    def test_empty_results(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "surt_prefix": "com,nomatch",
            "total_results": 0,
            "limit": 10,
            "results": [],
        }
        mock_get.return_value = mock_response

        args = argparse.Namespace(prefix="com,nomatch", limit=10)
        surt_prefix_cmd(args)

        out = json.loads(capsys.readouterr().out)
        assert out["results"] == []

    @patch("ccnget.api.requests.get")
    def test_request_error_exits(self, mock_get, capsys):
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError("boom")
        args = argparse.Namespace(prefix="com,aa", limit=10)
        with pytest.raises(SystemExit):
            surt_prefix_cmd(args)
        assert "boom" in capsys.readouterr().err


class TestSurtCliParsing:
    @patch("ccnget.api.requests.get")
    def test_surt_browse_subcommand(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "pattern": "",
            "count": 0,
            "total_entries": 1,
            "children": {},
            "total_children": 0,
            "offset": 0,
            "limit": 50,
            "next_offset": None,
        }
        mock_get.return_value = mock_response

        main(["surt-browse", "--limit", "5"])

        captured = capsys.readouterr()
        assert '"children"' in captured.out
        assert mock_get.call_args[1]["params"]["limit"] == 5

    @patch("ccnget.api.requests.get")
    def test_surt_browse_with_pattern(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "pattern": "com,aa",
            "count": 900,
            "total_entries": 1,
            "children": {},
            "total_children": 0,
            "offset": 0,
            "limit": 50,
            "next_offset": None,
        }
        mock_get.return_value = mock_response

        main(["surt-browse", "com,aa", "--offset", "10"])

        captured = capsys.readouterr()
        assert '"com,aa"' in captured.out
        assert mock_get.call_args[1]["params"] == {"pattern": "com,aa", "limit": 50, "offset": 10}

    @patch("ccnget.api.requests.get")
    def test_surt_prefix_subcommand(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "surt_prefix": "com,aa",
            "total_results": 0,
            "limit": 10,
            "results": [],
        }
        mock_get.return_value = mock_response

        main(["surt-prefix", "com,aa"])

        captured = capsys.readouterr()
        assert '"surt_prefix"' in captured.out
        assert mock_get.call_args[1]["params"] == {"prefix": "com,aa", "limit": 10}

    def test_surt_prefix_missing_prefix_fails(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["surt-prefix"])
        assert exc_info.value.code != 0

    def test_surt_browse_bad_limit_fails(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["surt-browse", "--limit", "500"])
        assert exc_info.value.code != 0

    def test_surt_browse_negative_offset_fails(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["surt-browse", "--offset", "-1"])
        assert exc_info.value.code != 0


class TestExceptions:
    def test_hierarchy(self):
        assert issubclass(NotFoundError, CcngetError)
        assert issubclass(NoRecordError, CcngetError)
        assert issubclass(CcngetError, Exception)
