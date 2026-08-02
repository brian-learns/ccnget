import argparse
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from warcio.archiveiterator import ArchiveIterator
from warcio.warcwriter import WARCWriter

from ccnget.geturl import fetch_cmd, lookup_cmd, limited_int, main, retrieve_cmd


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


class TestMainParsing:
    @patch("ccnget.geturl.requests.get")
    def test_lookup_subcommand(self, mock_get, capsys):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        main(["lookup", "http://example.com"])

        captured = capsys.readouterr()
        assert '"results"' in captured.out

    @patch("ccnget.geturl.requests.get")
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


class TestLookupCmd:
    @patch("ccnget.geturl.requests.get")
    def test_lookup_calls_api(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        args = argparse.Namespace(url="http://example.com", exact=False, limit=10, at=None)
        lookup_cmd(args)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "https://brian-learns-cc-news-cdx-server.hf.space/lookup"
        assert call_args[1]["params"]["url"] == "http://example.com"
        assert call_args[1]["params"]["exact"] is False
        assert call_args[1]["params"]["limit"] == 10
        assert call_args[1]["params"]["at"] is None

    @patch("ccnget.geturl.requests.get")
    def test_lookup_exact_flag(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        args = argparse.Namespace(url="http://example.com", exact=True, limit=5, at=None)
        lookup_cmd(args)

        call_args = mock_get.call_args
        assert call_args[1]["params"]["exact"] is True

    @patch("ccnget.geturl.requests.get")
    def test_lookup_at_parameter(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        args = argparse.Namespace(url="http://example.com", exact=False, limit=10, at="20240101120000")
        lookup_cmd(args)

        call_args = mock_get.call_args
        assert call_args[1]["params"]["at"] == "20240101120000"


class TestRetrieveCmd:
    @patch("ccnget.geturl.requests.get")
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

    @patch("ccnget.geturl.requests.get")
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

    @patch("ccnget.geturl.requests.get")
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
    @patch("ccnget.geturl.requests.get")
    def test_fetch_retrieves_first_result(self, mock_get, capsys):
        lookup_response = MagicMock()
        lookup_response.json.return_value = {
            "results": [
                {"surt_key": "com,example)/", "timestamp": "20170101000000", "warc_path": "test.warc.gz", "offset": 100, "length": 50}
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

    @patch("ccnget.geturl.requests.get")
    def test_fetch_with_at_parameter(self, mock_get, capsys):
        lookup_response = MagicMock()
        lookup_response.json.return_value = {
            "results": [
                {"surt_key": "com,example)/", "timestamp": "20170101000000", "warc_path": "test.warc.gz", "offset": 100, "length": 50}
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

    @patch("ccnget.geturl.requests.get")
    def test_fetch_with_output_file(self, mock_get, tmp_path):
        lookup_response = MagicMock()
        lookup_response.json.return_value = {
            "results": [
                {"surt_key": "com,example)/", "timestamp": "20170101000000", "warc_path": "test.warc.gz", "offset": 200, "length": 75}
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

    @patch("ccnget.geturl.requests.get")
    def test_fetch_no_results(self, mock_get, capsys):
        lookup_response = MagicMock()
        lookup_response.json.return_value = {"results": []}
        mock_get.return_value = lookup_response

        args = argparse.Namespace(url="http://nonexistent.example", exact=False, output=None, at=None)
        fetch_cmd(args)

        assert mock_get.call_count == 1
