"""Tests for ccnget.output: --select traversal, output modes, exit codes."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ccnget.output import (
    EXIT_API,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    SelectError,
    apply_select,
    emit,
    fail,
)

# Shared fixtures -----------------------------------------------------------

LOOKUP_PAYLOAD = {
    "url": "http://example.com",
    "results": [
        {
            "surt_key": "com,example)/",
            "timestamp": "20170101000000",
            "warc_path": "crawl-data/CC-NEWS/2017/01/a.warc.gz",
            "offset": 100,
            "length": 50,
        },
        {
            "surt_key": "com,example)/page2",
            "timestamp": "20180202000000",
            "warc_path": "crawl-data/CC-NEWS/2018/02/b.warc.gz",
            "offset": 200,
            "length": 75,
        },
    ],
}

CALLS: list[dict] = []


def _recording_renderer(payload: dict) -> None:
    """Stands in for a Rich renderer; records that it was used."""
    CALLS.append(payload)


def _mock_lookup_response(mock_get, results=None):
    """Point the mocked requests.get at a canned lookup response."""
    if results is None:
        results = [
            {
                "surt_key": "com,example)/",
                "timestamp": "20170101000000",
                "warc_path": "a.warc.gz",
                "offset": 1,
                "length": 2,
            }
        ]
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": results}
    mock_get.return_value = mock_response


# --select traversal ---------------------------------------------------------


class TestApplySelect:
    def test_top_level_field(self):
        assert apply_select(LOOKUP_PAYLOAD, "url") == "http://example.com"

    def test_indexed_entry_field(self):
        assert apply_select(LOOKUP_PAYLOAD, "results.0.warc_path") == "crawl-data/CC-NEWS/2017/01/a.warc.gz"

    def test_indexed_second_entry(self):
        assert apply_select(LOOKUP_PAYLOAD, "results.1.offset") == 200

    def test_map_over_list(self):
        assert apply_select(LOOKUP_PAYLOAD, "results.warc_path") == [
            "crawl-data/CC-NEWS/2017/01/a.warc.gz",
            "crawl-data/CC-NEWS/2018/02/b.warc.gz",
        ]

    def test_map_over_list_all_items(self):
        assert apply_select(LOOKUP_PAYLOAD, "results.length") == [50, 75]

    def test_index_into_top_level_list(self):
        assert apply_select({"results": ["a", "b"]}, "results.1") == "b"

    def test_missing_key_raises(self):
        with pytest.raises(SelectError, match="not found"):
            apply_select(LOOKUP_PAYLOAD, "nope")

    def test_missing_nested_key_raises(self):
        with pytest.raises(SelectError, match="not found"):
            apply_select(LOOKUP_PAYLOAD, "results.0.missing")

    def test_index_out_of_range_raises(self):
        with pytest.raises(SelectError, match="out of range"):
            apply_select(LOOKUP_PAYLOAD, "results.9")

    def test_traverse_into_scalar_raises(self):
        with pytest.raises(SelectError, match="cannot traverse"):
            apply_select(LOOKUP_PAYLOAD, "url.0")

    def test_string_key_that_looks_like_int(self):
        assert apply_select({"0": "zero"}, "0") == "zero"


# output modes ----------------------------------------------------------------


class TestEmitModes:
    def setup_method(self):
        CALLS.clear()

    def test_json_flag_pretty(self, capsys):
        code = emit(LOOKUP_PAYLOAD, _recording_renderer, json_flag=True)
        assert code == EXIT_OK
        out = capsys.readouterr().out
        assert json.loads(out) == LOOKUP_PAYLOAD
        assert '\n  "url"' in out  # indented

    def test_compact_single_line(self, capsys):
        code = emit(LOOKUP_PAYLOAD, _recording_renderer, compact=True)
        assert code == EXIT_OK
        out = capsys.readouterr().out
        assert len(out.strip().splitlines()) == 1
        assert ": " not in out  # no pretty separators

    def test_table_flag_calls_renderer(self, capsys):
        code = emit(LOOKUP_PAYLOAD, _recording_renderer, table_flag=True)
        assert code == EXIT_OK
        assert len(CALLS) == 1
        assert CALLS[0] is LOOKUP_PAYLOAD
        assert capsys.readouterr().out == ""

    def test_piped_default_is_pretty_json(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        code = emit(LOOKUP_PAYLOAD, _recording_renderer)
        assert code == EXIT_OK
        assert CALLS == []
        out = capsys.readouterr().out
        assert json.loads(out) == LOOKUP_PAYLOAD
        assert '\n  "url"' in out

    def test_interactive_default_uses_table(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        code = emit(LOOKUP_PAYLOAD, _recording_renderer)
        assert code == EXIT_OK
        assert len(CALLS) == 1
        assert capsys.readouterr().out == ""

    def test_compact_beats_json(self, capsys):
        code = emit(LOOKUP_PAYLOAD, _recording_renderer, json_flag=True, compact=True)
        assert code == EXIT_OK
        out = capsys.readouterr().out
        assert len(out.strip().splitlines()) == 1

    def test_select_wins_over_other_flags(self, capsys):
        code = emit(LOOKUP_PAYLOAD, _recording_renderer, json_flag=True, compact=True, select="url")
        assert code == EXIT_OK
        assert capsys.readouterr().out.strip() == "http://example.com"
        assert CALLS == []

    def test_select_map_over_list_is_json(self, capsys):
        code = emit(LOOKUP_PAYLOAD, _recording_renderer, select="results.warc_path")
        assert code == EXIT_OK
        out = capsys.readouterr().out
        assert json.loads(out) == [
            "crawl-data/CC-NEWS/2017/01/a.warc.gz",
            "crawl-data/CC-NEWS/2018/02/b.warc.gz",
        ]

    def test_select_bad_path_exits_usage(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            emit(LOOKUP_PAYLOAD, _recording_renderer, select="results.9")
        assert exc_info.value.code == EXIT_USAGE
        assert "selector" in capsys.readouterr().err

    def test_select_bad_path_machine_json_error(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            emit(LOOKUP_PAYLOAD, _recording_renderer, select="results.9", compact=True)
        assert exc_info.value.code == EXIT_USAGE
        payload = json.loads(capsys.readouterr().err)
        assert payload["status"] == "error"
        assert payload["code"] == EXIT_USAGE


# error reporting --------------------------------------------------------------


class TestFail:
    def test_human_error_goes_to_stderr(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            fail("no match for http://x", EXIT_NOT_FOUND)
        assert exc_info.value.code == EXIT_NOT_FOUND
        err = capsys.readouterr().err
        assert "no match for http://x" in err
        assert "error" in err

    def test_machine_error_is_json(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            fail("boom", EXIT_API, machine=True)
        assert exc_info.value.code == EXIT_API
        payload = json.loads(capsys.readouterr().err)
        assert payload == {"status": "error", "code": EXIT_API, "error": "boom"}

    def test_exit_code_constants(self):
        assert EXIT_OK == 0
        assert EXIT_USAGE == 2
        assert EXIT_NOT_FOUND == 3
        assert EXIT_API == 5


# argparse wiring ---------------------------------------------------------------


class TestOutputFlagParsing:
    def test_lookup_parser_has_output_flags(self):
        from ccnget.geturl import get_parser

        parser = get_parser()
        args = parser.parse_args(["lookup", "http://x", "--compact", "--select", "url"])
        assert args.compact is True
        assert args.json_flag is False
        assert args.table_flag is False
        assert args.select == "url"

    def test_default_output_flags_are_off(self):
        from ccnget.geturl import get_parser

        parser = get_parser()
        args = parser.parse_args(["extent"])
        assert args.json_flag is False
        assert args.compact is False
        assert args.table_flag is False
        assert args.select is None

    def test_all_four_json_subcommands_have_output_flags(self):
        from ccnget.geturl import get_parser

        parser = get_parser()
        for argv in (
            ["lookup", "http://x"],
            ["extent"],
            ["surt-browse", "com,aa"],
            ["surt-prefix", "com,aa"],
        ):
            args = parser.parse_args(argv + ["--json"])
            assert args.json_flag is True, argv

    def test_retrieve_and_fetch_have_no_output_flags(self):
        from ccnget.geturl import get_parser

        parser = get_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["retrieve", "--warc-path", "x", "--offset", "0", "--length", "1", "--json"]
            )
        with pytest.raises(SystemExit):
            parser.parse_args(["fetch", "http://x", "--json"])


# CLI end-to-end output modes -----------------------------------------------------


class TestCliOutputModes:
    @patch("ccnget.api.requests.get")
    def test_lookup_json(self, mock_get, capsys):
        from ccnget.geturl import main

        _mock_lookup_response(mock_get)
        main(["lookup", "http://example.com", "--json"])
        out = json.loads(capsys.readouterr().out)
        assert out["results"][0]["surt_key"] == "com,example)/"

    @patch("ccnget.api.requests.get")
    def test_lookup_compact(self, mock_get, capsys):
        from ccnget.geturl import main

        _mock_lookup_response(mock_get)
        main(["lookup", "http://example.com", "--compact"])
        out = capsys.readouterr().out
        assert len(out.strip().splitlines()) == 1
        assert json.loads(out)["results"][0]["offset"] == 1

    @patch("ccnget.api.requests.get")
    def test_lookup_select_bare_field(self, mock_get, capsys):
        from ccnget.geturl import main

        _mock_lookup_response(mock_get)
        main(["lookup", "http://example.com", "--select", "results.0.surt_key"])
        assert capsys.readouterr().out.strip() == "com,example)/"

    @patch("ccnget.api.requests.get")
    def test_lookup_piped_default_is_json(self, mock_get, capsys, monkeypatch):
        from ccnget.geturl import main

        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        _mock_lookup_response(mock_get)
        main(["lookup", "http://example.com"])
        out = capsys.readouterr().out
        assert json.loads(out)["results"][0]["warc_path"] == "a.warc.gz"

    @patch("ccnget.api.requests.get")
    def test_lookup_interactive_default_is_table(self, mock_get, capsys, monkeypatch):
        from ccnget.geturl import main

        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        _mock_lookup_response(mock_get)
        main(["lookup", "http://example.com"])
        out = capsys.readouterr().out
        # Rich table renders the row values; output is not JSON
        assert "com,example)/" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)

    @patch("ccnget.api.requests.get")
    def test_lookup_empty_results_exit_zero(self, mock_get, capsys):
        from ccnget.geturl import main

        _mock_lookup_response(mock_get, results=[])
        main(["lookup", "http://example.com", "--json"])
        out = json.loads(capsys.readouterr().out)
        assert out["results"] == []

    @patch("ccnget.api.requests.get")
    def test_lookup_api_error_machine_json(self, mock_get, capsys):
        import requests

        from ccnget.geturl import main

        mock_get.side_effect = requests.exceptions.ConnectionError("boom")
        with pytest.raises(SystemExit) as exc_info:
            main(["lookup", "http://example.com", "--json"])
        assert exc_info.value.code == EXIT_API
        payload = json.loads(capsys.readouterr().err)
        assert payload["code"] == EXIT_API
        assert "boom" in payload["error"]
