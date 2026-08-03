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

from ccnget.api import CDX_LOOKUP_URL, NotFoundError
from ccnget.api import fetch as api_fetch
from ccnget.api import lookup as api_lookup
from ccnget.api import retrieve as api_retrieve

logger: logging.Logger = logging.getLogger(__name__)


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
            f"ccnget: no match for {args.url} in {CDX_LOOKUP_URL}",
            file=sys.stderr,
        )
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
            f"ccnget: no match for {args.url} in {CDX_LOOKUP_URL}",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.output:
        from pathlib import Path

        Path(args.output).write_bytes(result.payload)
        logger.info("Wrote %d bytes to %s", len(result.payload), args.output)
    else:
        sys.stdout.buffer.write(result.payload)


def get_version() -> str:
    """Get version from pyproject.toml"""
    try:
        return version("ccnget")
    except PackageNotFoundError:
        return "unknown (local dev)"


def get_parser() -> argparse.ArgumentParser:
    """Build and return the ArgumentParser for ccnget."""
    _loglevel_: str = "WARNING"
    parser = argparse.ArgumentParser(description="lookup urls and get files from Common Crawl News")
    parser.add_argument(
        "--loglevel",
        default=_loglevel_,
        help="".join(["CRITICAL ERROR WARNING INFO DEBUG NOTSET, default is ", _loglevel_]),
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

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    """Parse CLI arguments and dispatch to subcommands."""
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


# main() idiom for importing into REPL for debugging
if __name__ == "__main__":
    sys.exit(main())


"""
Copyright © 2026, brian-learns and contributors
Copyright © 2015, Regents of the University of California
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

- Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.
- Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.
- Neither the name of the University of California nor the names of its
  contributors may be used to endorse or promote products derived from this
  software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""
