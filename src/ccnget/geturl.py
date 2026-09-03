"""CLI entry-point for ccnget.

Uses the library API (ccnget.api) for all logic and ccnget.output for
human/agent output formatting.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, NoReturn, Optional

import requests as _requests
from dotenv import load_dotenv

from ccnget.api import CcngetError, LookupEntry, NotFoundError
from ccnget.api import extent as api_extent
from ccnget.api import fetch as api_fetch
from ccnget.api import lookup as api_lookup
from ccnget.api import retrieve as api_retrieve
from ccnget.api import surt_browse as api_surt_browse
from ccnget.api import surt_prefix as api_surt_prefix
from ccnget.article import article as article_extract
from ccnget.article import article_to_dict, article_to_text
from ccnget.config import (
    get_config,
    list_config,
    set_config,
    show_config_path,
    unset_config,
)
from ccnget.output import (
    EXIT_API,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    emit,
    fail,
    render_extent,
    render_lookup,
    render_surt_browse,
)

logger: logging.Logger = logging.getLogger(__name__)

# Default log level -- override with --loglevel flag
DEFAULT_LOGLEVEL: str = "WARNING"


def limited_int(val_str: str) -> int:
    """Checks that input is an integer between 1 and 100."""
    try:
        val = int(val_str)
    except ValueError:
        # Add 'from None' to satisfy Ruff B904 and hide the ValueError traceback
        raise argparse.ArgumentTypeError("Must be an integer") from None

    if not (1 <= val <= 100):
        raise argparse.ArgumentTypeError("Value must be between 1 and 100")
    return val


def browse_limit(val_str: str) -> int:
    """Checks that input is an integer between 1 and 200 (surt-browse page size)."""
    try:
        val = int(val_str)
    except ValueError:
        # Add 'from None' to satisfy Ruff B904 and hide the ValueError traceback
        raise argparse.ArgumentTypeError("Must be an integer") from None

    if not (1 <= val <= 200):
        raise argparse.ArgumentTypeError("Value must be between 1 and 200")
    return val


def non_negative_int(val_str: str) -> int:
    """Checks that input is an integer of 0 or greater."""
    try:
        val = int(val_str)
    except ValueError:
        # Add 'from None' to satisfy Ruff B904 and hide the ValueError traceback
        raise argparse.ArgumentTypeError("Must be an integer") from None

    if val < 0:
        raise argparse.ArgumentTypeError("Value must be 0 or greater")
    return val


def _entry_dict(e: LookupEntry) -> dict[str, Any]:
    """One capture entry as a JSON-serialisable dict (extra fields merged)."""
    return {
        "surt_key": e.surt_key,
        "timestamp": e.timestamp,
        "warc_path": e.warc_path,
        "offset": e.offset,
        "length": e.length,
        **e.extra,
    }


def _output_flags(parser: argparse.ArgumentParser, table: bool = True) -> None:
    """Add the shared output-mode flags to a subcommand parser.

    Default: Rich table on an interactive TTY, pretty JSON when piped.
    --json / --compact / --table override in either direction; --select
    plucks a single value via dot notation and wins over all of them.
    ``table=False`` omits --table (subcommands with no table view).
    """
    group = parser.add_argument_group("output flags")
    group.add_argument("--json", dest="json_flag", action="store_true", help="Pretty-printed JSON output")
    group.add_argument("--compact", dest="compact", action="store_true", help="Minified single-line JSON output")
    if table:
        group.add_argument("--table", dest="table_flag", action="store_true", help="Force the human table view")
    group.add_argument(
        "--select",
        dest="select",
        metavar="PATH",
        help=(
            "Extract a value with dot notation and print it raw: "
            "results.0.warc_path, results.warc_path (maps over the list), or a top-level field like url"
        ),
    )


def _machine_mode(args: argparse.Namespace) -> bool:
    """True when errors should be reported as a JSON object on stderr."""
    return bool(args.json_flag or args.compact or args.select)


def _handle_request_error(exc: Exception, args: argparse.Namespace) -> NoReturn:
    """Report a transport/API failure with a typed exit code."""
    fail(f"request failed: {exc}", EXIT_API, machine=_machine_mode(args))


def lookup_cmd(args: argparse.Namespace) -> int:
    """Execute the lookup subcommand."""
    try:
        result = api_lookup(
            args.url,
            exact=args.exact,
            limit=args.limit,
            at=args.at,
        )
    except NotFoundError:
        fail(f"no match for {args.url}", EXIT_NOT_FOUND, machine=_machine_mode(args))
    except CcngetError as exc:
        fail(f"request failed: {exc}", EXIT_API, machine=_machine_mode(args))
    except _requests.exceptions.RequestException as exc:
        _handle_request_error(exc, args)

    output = {"url": result.url, "results": [_entry_dict(e) for e in result.entries]}
    title = f"Captures for {result.url}"
    return emit(output, lambda p: render_lookup(title, p), **_emit_kwargs(args))


def _emit_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    """Collect the shared output flags from a parsed namespace."""
    return {
        "json_flag": args.json_flag,
        "compact": args.compact,
        "table_flag": getattr(args, "table_flag", False),
        "select": args.select,
    }


def retrieve_cmd(args: argparse.Namespace) -> int:
    """Execute the retrieve subcommand."""
    try:
        result = api_retrieve(
            args.warc_path,
            args.offset,
            args.length,
        )
    except CcngetError as exc:
        fail(f"no response record: {exc}", EXIT_NOT_FOUND, machine=False)
    except _requests.exceptions.RequestException as exc:
        fail(f"request failed: {exc}", EXIT_API, machine=False)

    if args.output:
        Path(args.output).write_bytes(result.payload)
        logger.info("Wrote %d bytes to %s", len(result.payload), args.output)
    else:
        sys.stdout.buffer.write(result.payload)
    return 0


def fetch_cmd(args: argparse.Namespace) -> int:
    """Execute the fetch subcommand.

    Default: extract the first archived result as YAML frontmatter +
    markdown (article view). --json/--compact give structured JSON,
    --select plucks a field, --raw writes the raw payload bytes.
    """
    if args.raw:
        return _fetch_raw(args)

    try:
        res = article_extract(
            args.url,
            exact=args.exact,
            at=args.at,
        )
    except NotFoundError:
        fail(f"no match for {args.url}", EXIT_NOT_FOUND, machine=_machine_mode(args))
    except CcngetError as exc:
        fail(f"no response record: {exc}", EXIT_NOT_FOUND, machine=_machine_mode(args))
    except _requests.exceptions.RequestException as exc:
        _handle_request_error(exc, args)

    if res.fallback_level == 0:
        fail(
            f"no extractable text for {args.url} ({len(res.payload)} bytes); use --raw to get the raw payload",
            EXIT_API,
            machine=_machine_mode(args),
        )

    if args.select is not None:
        data = article_to_dict(res, mode=args.mode)
        return emit(data, _unused_renderer, select=args.select)

    data = article_to_dict(res, mode=args.mode)
    if args.quiet:
        data = {k: v for k, v in data.items() if k != "body"}

    if args.compact:
        print(json.dumps(data, separators=(",", ":")))
    elif args.json_flag:
        print(json.dumps(data, indent=2))
    else:
        text = article_to_text(res, mode=args.mode, quiet=args.quiet)
        if args.output:
            Path(args.output).write_text(text)
            logger.info("Wrote %d chars to %s", len(text), args.output)
        else:
            print(text)
    return EXIT_OK


def _unused_renderer(payload: dict[str, Any]) -> None:  # pragma: no cover
    """Placeholder renderer; fetch has no table view."""
    raise AssertionError("fetch has no table renderer")


def _fetch_raw(args: argparse.Namespace) -> int:
    """Fetch and write the raw payload bytes (previous fetch behaviour)."""
    try:
        result = api_fetch(
            args.url,
            exact=args.exact,
            at=args.at,
        )
    except NotFoundError:
        fail(f"no match for {args.url}", EXIT_NOT_FOUND, machine=False)
    except CcngetError as exc:
        fail(f"no response record: {exc}", EXIT_NOT_FOUND, machine=False)
    except _requests.exceptions.RequestException as exc:
        fail(f"request failed: {exc}", EXIT_API, machine=False)

    if args.output:
        Path(args.output).write_bytes(result.payload)
        logger.info("Wrote %d bytes to %s", len(result.payload), args.output)
    else:
        sys.stdout.buffer.write(result.payload)
    return 0


def tui_cmd(args: argparse.Namespace) -> int:
    """Execute the tui subcommand (Textual app; optional ``tui`` extra)."""
    try:
        from ccnget.tui import _tui_main
    except ImportError:
        fail(
            "the TUI requires the optional 'tui' extra: install with `uv pip install 'ccnget[tui]'` "
            "(or `pip install 'ccnget[tui]'`)",
            EXIT_USAGE,
            machine=False,
        )
    return _tui_main([f"--cdx-url={args.cdx_url}"] if args.cdx_url else [])


def config_cmd(args: argparse.Namespace) -> int:
    """Execute the config subcommand (set/get/show/unset)."""
    if args.config_action == "set":
        try:
            set_config(args.key, args.value)
        except KeyError as e:
            fail(f"config: {e}", EXIT_USAGE, machine=False)
        print(f"Set {args.key} = {args.value}")

    elif args.config_action == "get":
        val = get_config(args.key)
        if val is None:
            fail(f"config: {args.key} is not set in config file", EXIT_USAGE, machine=False)
        print(val)

    elif args.config_action == "show":
        cfg = list_config()
        print(f"Config file: {show_config_path()}")
        print()
        for key, info in cfg.items():
            print(f"  {key} = {info['value']}")
            print(f"    source: {info['source']}")

    elif args.config_action == "unset":
        try:
            unset_config(args.key)
        except KeyError as e:
            fail(f"config: {e}", EXIT_USAGE, machine=False)
        print(f"Unset {args.key}")
    return 0


def get_version() -> str:
    """Get version from pyproject.toml"""
    try:
        return version("ccnget")
    except PackageNotFoundError:
        return "unknown (local dev)"


def get_parser() -> argparse.ArgumentParser:
    """Build and return the ArgumentParser for ccnget."""
    parser = argparse.ArgumentParser(description="lookup urls and get files from Common Crawl News")
    parser.add_argument(
        "--loglevel",
        default=DEFAULT_LOGLEVEL,
        help="CRITICAL ERROR WARNING INFO DEBUG NOTSET, default is " + DEFAULT_LOGLEVEL,
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {get_version()}")

    subparsers = parser.add_subparsers(
        title="subcommands",
        metavar="",
        dest="command",
        required=True,
    )

    # lookup subcommand
    lookup_parser = subparsers.add_parser("lookup", help="Lookup URLs in CC-NEWS index")
    lookup_parser.add_argument("url")
    lookup_parser.add_argument("--exact", action="store_true")
    lookup_parser.add_argument(
        "--at",
        help="Timestamp (YYYYMMDDhhmmss). Seeks from timestamp if exact=True, finds closest match if exact=False.",
    )
    lookup_parser.add_argument("--limit", type=limited_int, default=10, help="Limit value (1-100, default: 10)")
    _output_flags(lookup_parser)

    # retrieve subcommand
    retrieve_parser = subparsers.add_parser("retrieve", help="Retrieve WARC records from Common Crawl")
    retrieve_parser.add_argument("--warc-path", required=True, help="WARC path from lookup results")
    retrieve_parser.add_argument("--offset", type=int, required=True, help="Byte offset in WARC file")
    retrieve_parser.add_argument("--length", type=int, required=True, help="Byte length of record")
    retrieve_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # fetch subcommand (lookup + retrieve + extract first result)
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Lookup and fetch the first result as an article (YAML frontmatter + markdown)",
    )
    fetch_parser.add_argument("url")
    fetch_parser.add_argument("--exact", action="store_true")
    fetch_parser.add_argument(
        "--at",
        help="Timestamp (YYYYMMDDhhmmss). Seeks from timestamp if exact=True, finds closest match if exact=False.",
    )
    fetch_parser.add_argument(
        "--mode",
        "-m",
        choices=["full", "brief"],
        default="full",
        help="'full' = complete article, 'brief' = first paragraph (default: full)",
    )
    fetch_parser.add_argument("--quiet", "-q", action="store_true", help="Metadata only, no article body")
    fetch_parser.add_argument("--raw", action="store_true", help="Write the raw payload bytes (previous default)")
    fetch_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    _output_flags(fetch_parser, table=False)

    # config subcommand (set/get/show/unset persistent settings)
    config_sub = subparsers.add_parser("config", help="Manage persistent settings").add_subparsers(
        dest="config_action", required=True
    )

    set_p = config_sub.add_parser("set", help="Set a config value")
    set_p.add_argument("key", choices=["cdx-url", "cc-crawl-base-url"])
    set_p.add_argument("value")

    get_p = config_sub.add_parser("get", help="Get a config value")
    get_p.add_argument("key", choices=["cdx-url", "cc-crawl-base-url"])

    config_sub.add_parser("show", help="Show all config values and sources")

    unset_p = config_sub.add_parser("unset", help="Remove a config value")
    unset_p.add_argument("key", choices=["cdx-url", "cc-crawl-base-url"])

    # extent subcommand (show index statistics)
    extent_parser = subparsers.add_parser("extent", help="Show what content is indexed on the server")
    _output_flags(extent_parser)

    # surt-browse subcommand (browse the SURT host tree one level at a time)
    surt_browse_parser = subparsers.add_parser("surt-browse", help="Browse hosts indexed on the server")
    surt_browse_parser.add_argument(
        "pattern",
        nargs="?",
        default="",
        help="Pattern to expand (default: root level). Use a child pattern from a previous result to go deeper.",
    )
    surt_browse_parser.add_argument(
        "--limit",
        type=browse_limit,
        default=50,
        help="Maximum number of children to return (1-200, default: 50)",
    )
    surt_browse_parser.add_argument(
        "--offset",
        type=non_negative_int,
        default=0,
        help="Children to skip before applying limit (default: 0)",
    )
    _output_flags(surt_browse_parser)

    # surt-prefix subcommand (wildcard search of captures under a SURT prefix)
    surt_prefix_parser = subparsers.add_parser("surt-prefix", help="Prefix search surts indexed on the server")
    surt_prefix_parser.add_argument(
        "prefix",
        help="SURT prefix to scan, e.g. com,aa or com,aaa,ace)/activities",
    )
    surt_prefix_parser.add_argument("--limit", type=limited_int, default=10, help="Limit value (1-100, default: 10)")
    _output_flags(surt_prefix_parser)

    # tui subcommand (Textual terminal UI; optional 'tui' extra)
    tui_parser = subparsers.add_parser(
        "tui",
        help="Interactive TUI: SURT tree browse, prefix scan, and article reader (requires the 'tui' extra)",
    )
    tui_parser.add_argument(
        "--cdx-url",
        default=None,
        help="CDX server base URL override (default: config file > CDX_URL env > built-in)",
    )

    return parser


def extent_cmd(args: argparse.Namespace) -> int:
    """Execute the extent subcommand."""
    try:
        result = api_extent()
    except CcngetError as exc:
        fail(f"request failed: {exc}", EXIT_API, machine=_machine_mode(args))
    except _requests.exceptions.RequestException as exc:
        _handle_request_error(exc, args)

    return emit(result.__dict__, render_extent, **_emit_kwargs(args))


def surt_browse_cmd(args: argparse.Namespace) -> int:
    """Execute the surt-browse subcommand."""
    try:
        result = api_surt_browse(
            args.pattern,
            limit=args.limit,
            offset=args.offset,
        )
    except CcngetError as exc:
        fail(f"request failed: {exc}", EXIT_API, machine=_machine_mode(args))
    except _requests.exceptions.RequestException as exc:
        _handle_request_error(exc, args)

    return emit(result.__dict__, render_surt_browse, **_emit_kwargs(args))


def surt_prefix_cmd(args: argparse.Namespace) -> int:
    """Execute the surt-prefix subcommand."""
    try:
        result = api_surt_prefix(
            args.prefix,
            limit=args.limit,
        )
    except CcngetError as exc:
        fail(f"request failed: {exc}", EXIT_API, machine=_machine_mode(args))
    except _requests.exceptions.RequestException as exc:
        _handle_request_error(exc, args)

    # Build a JSON-serialisable dict in the lookup output style
    output = {
        "surt_prefix": result.surt_prefix,
        "total_results": result.total_results,
        "limit": result.limit,
        "results": [_entry_dict(e) for e in result.results],
    }
    title = f"Captures under {result.surt_prefix}"
    return emit(output, lambda p: render_lookup(title, p), **_emit_kwargs(args))


def main(argv: Optional[list[str]] = None) -> int:
    """Parse CLI arguments and dispatch to subcommands.

    Returns a typed exit code: 0 ok, 2 usage, 3 not found, 5 API error.
    Error paths exit immediately via ccnget.output.fail().
    """
    load_dotenv()

    args = get_parser().parse_args(argv)

    # set debugging level
    numeric_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: %s" % args.loglevel)
    logging.basicConfig(
        level=numeric_level,
    )

    code = 0
    if args.command == "lookup":
        code = lookup_cmd(args)
    elif args.command == "retrieve":
        code = retrieve_cmd(args)
    elif args.command == "fetch":
        code = fetch_cmd(args)
    elif args.command == "config":
        code = config_cmd(args)
    elif args.command == "extent":
        code = extent_cmd(args)
    elif args.command == "surt-browse":
        code = surt_browse_cmd(args)
    elif args.command == "surt-prefix":
        code = surt_prefix_cmd(args)
    elif args.command == "tui":
        code = tui_cmd(args)
    return code


# main() idiom for importing into REPL for debugging
if __name__ == "__main__":
    sys.exit(main())
