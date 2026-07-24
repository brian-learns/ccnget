import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import requests

logger: logging.Logger = logging.getLogger(__name__)

BASE_URL = "https://brian-learns-cc-news-cdx-server.hf.space/lookup"


def valid_dir(path_string: str) -> Path:
    """valid_dir helper for argparse"""
    path: Path = Path(path_string)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"'{path_string}' is not a directory.")
    return path


def limited_int(val_str):
    """Checks that input is an integer between 1 and 1000."""
    try:
        val = int(val_str)
    except ValueError:
        # Add 'from None' to satisfy Ruff B904 and hide the ValueError traceback
        raise argparse.ArgumentTypeError("Must be an integer") from None

    if not (1 <= val <= 1000):
        raise argparse.ArgumentTypeError("Value must be between 1 and 1000")
    return val


def main(argv: Optional[argparse.Namespace] = None) -> None:
    """ """
    _loglevel_: str = "WARNING"
    parser = argparse.ArgumentParser(description="get from CC-NEWS")
    parser.add_argument("url")
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--limit", type=limited_int, default=100, help="Limit value (1-1000, default: 100)")
    parser.add_argument(
        "--loglevel",
        default=_loglevel_,
        help="".join(["CRITICAL ERROR WARNING INFO DEBUG NOTSET, default is ", _loglevel_]),
    )

    if argv is None:
        argv = parser.parse_args()

    # set debugging level
    numeric_level: Optional[int] = getattr(logging, argv.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: %s" % argv.loglevel)
    logging.basicConfig(
        level=numeric_level,
    )

    params = {
        "url": argv.url,
        "exact": argv.exact,
        "limit": argv.limit,
    }

    logger.debug("Requesting %s with params %s", BASE_URL, params)

    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()

    print(json.dumps(response.json(), indent=2))


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
