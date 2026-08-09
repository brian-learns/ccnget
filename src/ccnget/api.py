"""Public library API for ccnget.

Lookup and retrieve archived web pages from the Common Crawl News dataset.

Example
-------
```
>>> import ccnget
>>> result = ccnget.fetch("http://example.com")
>>> print(result.surt_key, result.timestamp)
>>> tree = LexborHTMLParser(result.payload)
```
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import requests
from dotenv import load_dotenv
from warcio.archiveiterator import ArchiveIterator

from ccnget.config import KNOWN_KEYS, _resolve

load_dotenv()

logger: logging.Logger = logging.getLogger(__name__)

# Hard-coded defaults (overridden by config file or env vars at runtime)
CDX_LOOKUP_URL: str = KNOWN_KEYS["cdx-url"][0]
CC_CRAWL_BASE_URL: str = KNOWN_KEYS["cc-crawl-base-url"][0]


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class LookupEntry:
    """One CDX index hit returned by the lookup API."""

    surt_key: str
    timestamp: str
    warc_path: str
    offset: int
    length: int
    # Extra fields from the API (if any) are stored here
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LookupResult:
    """Result of a CDX index lookup."""

    url: str
    entries: list[LookupEntry]


@dataclass
class FetchResult:
    """Result of fetching an archived page.

    Attributes
    ----------
    payload : bytes
        Raw response body (typically HTML).
    http_headers : dict[str, str]
        HTTP response headers from inside the WARC record.
    warc_headers : dict[str, str]
        WARC record headers.
    surt_key : str
        SURT-formatted URL key from the CDX index.
    timestamp : str
        WARC timestamp (YYYYMMDDhhmmss).
    warc_path : str
        Path to the WARC file on Common Crawl storage.
    """

    payload: bytes
    http_headers: dict[str, str]
    warc_headers: dict[str, str]
    surt_key: str
    timestamp: str
    warc_path: str


# ── Helpers ───────────────────────────────────────────────────────────────


def _headers_to_dict(headers: Any) -> dict[str, str]:
    """Convert a warcio Header object to a plain dict."""
    if headers is None:
        return {}
    # warcio Header objects have a .headers list of (name, value) tuples
    return dict(headers.headers)


def _entry_from_dict(d: dict[str, Any]) -> LookupEntry:
    """Build a LookupEntry from a raw CDX JSON dict."""
    known = {"surt_key", "timestamp", "warc_path", "offset", "length"}
    base = {k: d[k] for k in known if k in d}
    extra = {k: v for k, v in d.items() if k not in known}
    return LookupEntry(extra=extra, **base)  # type: ignore[arg-type]


# ── Public API ────────────────────────────────────────────────────────────


def lookup(
    url: str,
    *,
    exact: bool = False,
    limit: int = 10,
    at: str | None = None,
    cdx_url: str | None = None,
) -> LookupResult:
    """Search the CC-NEWS CDX index for *url*.

    Parameters
    ----------
    url : str
        URL to search for.
    exact : bool
        Require exact match.
    limit : int
        Maximum number of results (1-100).
    at : str | None
        Timestamp filter (YYYYMMDDhhmmss).
    cdx_url : str | None
        Override the CDX lookup endpoint. Falls back to config file,
        then environment variable ``CDX_LOOKUP_URL``, then hard-coded default.

    Returns
    -------
    LookupResult
    """
    if cdx_url is None:
        cdx_url = _resolve(
            "cdx-url",
            default=CDX_LOOKUP_URL,
            env_var="CDX_LOOKUP_URL",
        )
    params = {"url": url, "exact": exact, "limit": limit, "at": at}
    logger.debug("Requesting %s with params %s", cdx_url, params)

    response = requests.get(cdx_url, params=params, timeout=30)
    if response.status_code == 404:
        raise NotFoundError(f"No match for {url} in {cdx_url}")
    response.raise_for_status()

    data = response.json()
    entries = [_entry_from_dict(r) for r in data.get("results", [])]
    return LookupResult(url=url, entries=entries)


def retrieve(
    warc_path: str,
    offset: int,
    length: int,
    *,
    base_url: str | None = None,
    surt_key: str = "",
    timestamp: str = "",
) -> FetchResult:
    """Retrieve a single WARC record via byte-range request.

    Parameters
    ----------
    warc_path : str
        Path within Common Crawl storage (e.g. ``crawl-data/CC-NEWS/...``).
    offset : int
        Byte offset of the record.
    length : int
        Byte length of the record.
    base_url : str | None
        Override the Common Crawl base URL. Falls back to config file,
        then environment variable ``CC_CRAWL_BASE_URL``, then hard-coded default.
    surt_key : str
        SURT key from the CDX index (populated by ``fetch()``).
    timestamp : str
        Timestamp from the CDX index (populated by ``fetch()``).

    Returns
    -------
    FetchResult
    """
    if base_url is None:
        base_url = _resolve(
            "cc-crawl-base-url",
            default=CC_CRAWL_BASE_URL,
            env_var="CC_CRAWL_BASE_URL",
        )
    warc_url = f"{base_url}/{warc_path}"
    start = offset
    end = start + length - 1

    headers = {"Range": f"bytes={start}-{end}"}
    logger.debug("Requesting %s Range: bytes=%d-%d", warc_url, start, end)

    response = requests.get(warc_url, headers=headers, timeout=60)
    response.raise_for_status()

    for record in ArchiveIterator(BytesIO(response.content)):
        if record.rec_type == "response":
            payload = record.content_stream().read()
            logger.debug("WARC Headers:\n%s", record.rec_headers)
            return FetchResult(
                payload=payload,
                http_headers=_headers_to_dict(record.http_headers),
                warc_headers=_headers_to_dict(record.rec_headers),
                surt_key=surt_key,
                timestamp=timestamp,
                warc_path=warc_path,
            )

    raise NoRecordError(f"No response record found in WARC data at {warc_path}:{offset}")


def fetch(
    url: str,
    *,
    exact: bool = False,
    at: str | None = None,
    cdx_url: str | None = None,
    base_url: str | None = None,
) -> FetchResult:
    """Lookup *url* in the CDX index and retrieve the first archived result.

    Convenience wrapper around :func:`lookup` + :func:`retrieve`.

    Parameters
    ----------
    url : str
        URL to search for.
    exact : bool
        Require exact match.
    at : str | None
        Timestamp filter (YYYYMMDDhhmmss).
    cdx_url : str | None
        Override the CDX lookup endpoint. Falls back to config file,
        then environment variable ``CDX_LOOKUP_URL``, then hard-coded default.
    base_url : str | None
        Override the Common Crawl base URL. Falls back to config file,
        then environment variable ``CC_CRAWL_BASE_URL``, then hard-coded default.

    Returns
    -------
    FetchResult
    """
    result = lookup(url, exact=exact, at=at, limit=1, cdx_url=cdx_url)
    if not result.entries:
        raise NotFoundError(f"No archived results for {url}")

    first = result.entries[0]
    logger.info("Found: %s at %s", first.surt_key, first.timestamp)
    return retrieve(
        first.warc_path,
        first.offset,
        first.length,
        base_url=base_url,
        surt_key=first.surt_key,
        timestamp=first.timestamp,
    )


# ── Exceptions ────────────────────────────────────────────────────────────


class CcngetError(Exception):
    """Base exception for ccnget."""


class NotFoundError(CcngetError):
    """Raised when a URL has no matches in the CDX index."""


class NoRecordError(CcngetError):
    """Raised when a WARC segment contains no response record."""
