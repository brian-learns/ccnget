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
from warcio.archiveiterator import ArchiveIterator

from ccnget.config import KNOWN_KEYS, _resolve
from ccnget.retry import retry_with_backoff

logger: logging.Logger = logging.getLogger(__name__)

# Hard-coded defaults (overridden by config file or env vars at runtime)
CDX_URL: str = KNOWN_KEYS["cdx-url"][0]
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


@dataclass
class ExtentResult:
    """Result of querying the extent endpoint.

    Attributes
    ----------
    file_extent : int
        Number of files covered by this index.
    file_oldest : str
        First WARC file in this index.
    file_newest : str
        Last WARC file added to this index.
    """

    file_extent: int
    file_oldest: str
    file_newest: str


@dataclass
class SurtBrowseResult:
    """Result of one hop down the SURT host tree.

    Attributes
    ----------
    pattern : str
        Pattern browsed (``''`` is the root level).
    count : int
        Indexed entries under this exact host pattern.
    total_entries : int
        Total entries in the whole index.
    children : dict[str, int]
        Direct children (pattern -> count), rank order (count desc, name asc),
        capped by ``limit``. Each key is also the ``pattern`` to fetch the
        next level.
    total_children : int
        Number of children before ``limit`` was applied.
    offset : int
        Children skipped before this page (0-based).
    limit : int
        Page size that was applied.
    next_offset : int | None
        Offset for the next page; ``None`` on the last page.
    """

    pattern: str
    count: int
    total_entries: int
    children: dict[str, int]
    total_children: int
    offset: int = 0
    limit: int = 50
    next_offset: int | None = None


@dataclass
class SurtScanResult:
    """Result of a SURT prefix scan.

    Attributes
    ----------
    surt_prefix : str
        SURT string used for the lookup.
    total_results : int
        Number of results returned (capped by ``limit``, not a true total).
    limit : int
        Maximum results cap requested.
    results : list[LookupEntry]
        Matched WARC captures in key order (SURT, then timestamp).
    """

    surt_prefix: str
    total_results: int
    limit: int
    results: list[LookupEntry]


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


# Trailing endpoint paths that may be stored in a legacy ``cdx-url`` value.
# Checked longest-first so ``…/cdx-index/lookup`` isn't misread as ``…/lookup``.
_CDX_ENDPOINT_SUFFIXES: tuple[str, ...] = (
    "/cdx-index/lookup",
    "/lookup",
)


def _cdx_base(url: str) -> str:
    """Normalize a configured ``cdx-url`` value to a server base URL.

    ``cdx-url`` is a server *base* URL; the client appends the endpoint
    paths (``/cdx-index/lookup``, ``/cdx-index/extent``). Older
    configurations may still store an endpoint URL instead — a trailing
    ``/lookup`` (or the new ``/cdx-index/lookup`` form) is stripped so
    those values keep working.

    >>> _cdx_base("https://host/")
    'https://host'
    >>> _cdx_base("https://host/lookup")
    'https://host'
    >>> _cdx_base("https://host/cdx-index/lookup")
    'https://host'
    >>> _cdx_base("http://0.0.0.0:8000/lookup/")
    'http://0.0.0.0:8000'
    """
    base = url.rstrip("/")
    for suffix in _CDX_ENDPOINT_SUFFIXES:
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


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
        Override the CDX server base URL. Falls back to config file,
        then environment variable ``CDX_URL``, then hard-coded default.

    Returns
    -------
    LookupResult
    """
    if cdx_url is None:
        cdx_url = _resolve(
            "cdx-url",
            default=CDX_URL,
            env_var="CDX_URL",
        )
    lookup_url = _cdx_base(cdx_url) + "/cdx-index/lookup"
    params = {"url": url, "exact": exact, "limit": limit, "at": at}
    logger.debug("Requesting %s with params %s", lookup_url, params)

    data = retry_with_backoff(lambda: requests.get(lookup_url, params=params, timeout=30)).json()
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

    response = retry_with_backoff(lambda: requests.get(warc_url, headers=headers, timeout=60))

    # S3 returns 206 Partial Content for Range requests; 200 is also acceptable
    if isinstance(response.status_code, int) and response.status_code not in (200, 206):
        raise RuntimeError(f"Unexpected status {response.status_code} for range request to {warc_url}")

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
        Override the CDX server base URL. Falls back to config file,
        then environment variable ``CDX_URL``, then hard-coded default.
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


def extent(
    *,
    cdx_url: str | None = None,
) -> ExtentResult:
    """Query the extent endpoint for index statistics.

    Parameters
    ----------
    cdx_url : str | None
        Override the CDX server base URL. The ``/cdx-index/extent`` path is
        appended to the base. Falls back to config file, then environment
        variable ``CDX_URL``, then hard-coded default.

    Returns
    -------
    ExtentResult
    """
    if cdx_url is None:
        cdx_url = _resolve(
            "cdx-url",
            default=CDX_URL,
            env_var="CDX_URL",
        )
    extent_url = _cdx_base(cdx_url) + "/cdx-index/extent"
    logger.debug("Requesting extent from %s", extent_url)

    data = retry_with_backoff(lambda: requests.get(extent_url, timeout=30)).json()
    return ExtentResult(
        file_extent=data["file_extent"],
        file_oldest=data["file_oldest"],
        file_newest=data["file_newest"],
    )


def surt_browse(
    pattern: str = "",
    *,
    limit: int = 50,
    offset: int = 0,
    cdx_url: str | None = None,
) -> SurtBrowseResult:
    """Browse the index's SURT host tree one level at a time.

    Parameters
    ----------
    pattern : str
        Pattern to expand; ``''`` (default) is the root level. Children
        returned by a previous call can be passed back in to descend one
        more level.
    limit : int
        Maximum number of children to return (1-200, default 50).
    offset : int
        Children to skip before applying ``limit`` (default 0).
    cdx_url : str | None
        Override the CDX server base URL. The ``/cdx-index/surt-browse``
        path is appended to the base. Falls back to config file, then
        environment variable ``CDX_URL``, then hard-coded default.

    Returns
    -------
    SurtBrowseResult
    """
    if cdx_url is None:
        cdx_url = _resolve(
            "cdx-url",
            default=CDX_URL,
            env_var="CDX_URL",
        )
    browse_url = _cdx_base(cdx_url) + "/cdx-index/surt-browse"
    params = {"pattern": pattern, "limit": limit, "offset": offset}
    logger.debug("Requesting %s with params %s", browse_url, params)

    data = retry_with_backoff(lambda: requests.get(browse_url, params=params, timeout=30)).json()
    return SurtBrowseResult(
        pattern=data["pattern"],
        count=data["count"],
        total_entries=data["total_entries"],
        children=data["children"],
        total_children=data["total_children"],
        offset=data.get("offset", offset),
        limit=data.get("limit", limit),
        next_offset=data.get("next_offset"),
    )


def surt_prefix(
    prefix: str,
    *,
    limit: int = 10,
    cdx_url: str | None = None,
) -> SurtScanResult:
    """Wildcard search: find capture records under a SURT prefix.

    Parameters
    ----------
    prefix : str
        SURT string to scan, e.g. ``com,aa`` (host + subdomains) or
        ``com,aaa,ace)/activities`` (path prefix of ace.aaa.com).
    limit : int
        Maximum number of results to return (1-100, default 10).
    cdx_url : str | None
        Override the CDX server base URL. The ``/cdx-index/surt-prefix``
        path is appended to the base. Falls back to config file, then
        environment variable ``CDX_URL``, then hard-coded default.

    Returns
    -------
    SurtScanResult
        Results in key order (SURT, then timestamp). ``total_results`` is
        the number returned, not a true total.
    """
    if cdx_url is None:
        cdx_url = _resolve(
            "cdx-url",
            default=CDX_URL,
            env_var="CDX_URL",
        )
    scan_url = _cdx_base(cdx_url) + "/cdx-index/surt-prefix"
    params = {"prefix": prefix, "limit": limit}
    logger.debug("Requesting %s with params %s", scan_url, params)

    data = retry_with_backoff(lambda: requests.get(scan_url, params=params, timeout=30)).json()
    return SurtScanResult(
        surt_prefix=data["surt_prefix"],
        total_results=data["total_results"],
        limit=data["limit"],
        results=[_entry_from_dict(r) for r in data.get("results", [])],
    )


# ── Exceptions ────────────────────────────────────────────────────────────


class CcngetError(Exception):
    """Base exception for ccnget."""


class NotFoundError(CcngetError):
    """Raised when a URL has no matches in the CDX index."""


class NoRecordError(CcngetError):
    """Raised when a WARC segment contains no response record."""
