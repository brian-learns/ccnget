"""CLI entry-point for ccnget.

Uses the library API (ccnget.api) for all logic.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Optional

import requests as _requests
from dotenv import load_dotenv

from ccnget.api import NotFoundError
from ccnget.api import extent as api_extent
from ccnget.api import fetch as api_fetch
from ccnget.api import lookup as api_lookup
from ccnget.api import retrieve as api_retrieve
from ccnget.config import (
    get_config,
    list_config,
    set_config,
    show_config_path,
    unset_config,
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


def lookup_cmd(args: argparse.Namespace) -> None:
    """Execute the lookup subcommand."""
    try:
        result = api_lookup(
            args.url,
            exact=args.exact,
            limit=args.limit,
            at=args.at,
        )
    except NotFoundError:
        print(
            f"ccnget: no match for {args.url}",
            file=sys.stderr,
        )
        sys.exit(1)
    except _requests.exceptions.RequestException as exc:
        print(f"ccnget: {exc}", file=sys.stderr)
        sys.exit(1)

    # Build a JSON-serialisable dict matching the old format
    output = {
        "url": result.url,
        "results": [
            {
                "surt_key": e.surt_key,
                "timestamp": e.timestamp,
                "warc_path": e.warc_path,
                "offset": e.offset,
                "length": e.length,
                **e.extra,
            }
            for e in result.entries
        ],
    }
    print(json.dumps(output, indent=2))


def retrieve_cmd(args: argparse.Namespace) -> None:
    """Execute the retrieve subcommand."""
    result = api_retrieve(
        args.warc_path,
        args.offset,
        args.length,
    )

    if args.output:
        from pathlib import Path

        Path(args.output).write_bytes(result.payload)
        logger.info("Wrote %d bytes to %s", len(result.payload), args.output)
    else:
        sys.stdout.buffer.write(result.payload)


def fetch_cmd(args: argparse.Namespace) -> None:
    """Execute the fetch subcommand: lookup then retrieve the first result."""
    try:
        result = api_fetch(
            args.url,
            exact=args.exact,
            at=args.at,
        )
    except NotFoundError:
        print(
            f"ccnget: no match for {args.url}",
            file=sys.stderr,
        )
        sys.exit(1)
    except _requests.exceptions.RequestException as exc:
        print(f"ccnget: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        from pathlib import Path

        Path(args.output).write_bytes(result.payload)
        logger.info("Wrote %d bytes to %s", len(result.payload), args.output)
    else:
        sys.stdout.buffer.write(result.payload)


def config_cmd(args: argparse.Namespace) -> None:
    """Execute the config subcommand (set/get/show/unset)."""
    if args.config_action == "set":
        try:
            set_config(args.key, args.value)
        except KeyError as e:
            print(f"ccnget: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Set {args.key} = {args.value}")

    elif args.config_action == "get":
        val = get_config(args.key)
        if val is None:
            print(f"ccnget: {args.key} is not set in config file", file=sys.stderr)
            sys.exit(1)
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
            print(f"ccnget: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Unset {args.key}")


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

    subparsers = parser.add_subparsers(dest="command", required=True)

    # lookup subcommand
    lookup_parser = subparsers.add_parser("lookup", help="Lookup URLs in CC-NEWS index")
    lookup_parser.add_argument("url")
    lookup_parser.add_argument("--exact", action="store_true")
    lookup_parser.add_argument(
        "--at",
        help="Timestamp (YYYYMMDDhhmmss). Seeks from timestamp if exact=True, finds closest match if exact=False.",
    )
    lookup_parser.add_argument("--limit", type=limited_int, default=10, help="Limit value (1-100, default: 10)")

    # retrieve subcommand
    retrieve_parser = subparsers.add_parser("retrieve", help="Retrieve WARC records from Common Crawl")
    retrieve_parser.add_argument("--warc-path", required=True, help="WARC path from lookup results")
    retrieve_parser.add_argument("--offset", type=int, required=True, help="Byte offset in WARC file")
    retrieve_parser.add_argument("--length", type=int, required=True, help="Byte length of record")
    retrieve_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # fetch subcommand (lookup + retrieve first result)
    fetch_parser = subparsers.add_parser("fetch", help="Lookup and retrieve the first result")
    fetch_parser.add_argument("url")
    fetch_parser.add_argument("--exact", action="store_true")
    fetch_parser.add_argument(
        "--at",
        help="Timestamp (YYYYMMDDhhmmss). Seeks from timestamp if exact=True, finds closest match if exact=False.",
    )
    fetch_parser.add_argument("--output", "-o", help="Output file path (default: stdout)")

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
    subparsers.add_parser("extent", help="Show what content is indexed on the server")

    return parser


def extent_cmd(args: argparse.Namespace) -> None:
    """Execute the extent subcommand."""
    result = api_extent()
    print(json.dumps(result.__dict__, indent=2))


def main(argv: Optional[list[str]] = None) -> None:
    """Parse CLI arguments and dispatch to subcommands."""
    load_dotenv()

    args = get_parser().parse_args(argv)

    # set debugging level
    numeric_level: Optional[int] = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: %s" % args.loglevel)
    logging.basicConfig(
        level=numeric_level,
    )

    if args.command == "lookup":
        lookup_cmd(args)
    elif args.command == "retrieve":
        retrieve_cmd(args)
    elif args.command == "fetch":
        fetch_cmd(args)
    elif args.command == "config":
        config_cmd(args)
    elif args.command == "extent":
        extent_cmd(args)


# main() idiom for importing into REPL for debugging
if __name__ == "__main__":
    sys.exit(main())
