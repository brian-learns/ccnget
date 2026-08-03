<a id="ccnget"></a>

# ccnget

ccnget -- lookup URLs and get archived pages from Common Crawl News.

Library usage
-------------
```
>>> import ccnget
>>> result = ccnget.fetch("http://example.com")
>>> print(result.surt_key, result.timestamp)
>>> # Parse with any HTML parser
>>> from selectolax.lexbor import LexborHTMLParser
>>> tree = LexborHTMLParser(result.payload)

Or use the lower-level API:
>>> lr = ccnget.lookup("http://example.com", limit=5)
>>> for entry in lr.entries:
...     result = ccnget.retrieve(entry.warc_path, entry.offset, entry.length)
```

<a id="ccnget.geturl"></a>

# ccnget.geturl

CLI entry-point for ccnget.

Uses the library API (ccnget.api) for all logic.

<a id="ccnget.geturl.limited_int"></a>

#### limited\_int

```python
def limited_int(val_str: str) -> int
```

Checks that input is an integer between 1 and 100.

<a id="ccnget.geturl.lookup_cmd"></a>

#### lookup\_cmd

```python
def lookup_cmd(args: argparse.Namespace) -> None
```

Execute the lookup subcommand.

<a id="ccnget.geturl.retrieve_cmd"></a>

#### retrieve\_cmd

```python
def retrieve_cmd(args: argparse.Namespace) -> None
```

Execute the retrieve subcommand.

<a id="ccnget.geturl.fetch_cmd"></a>

#### fetch\_cmd

```python
def fetch_cmd(args: argparse.Namespace) -> None
```

Execute the fetch subcommand: lookup then retrieve the first result.

<a id="ccnget.geturl.get_version"></a>

#### get\_version

```python
def get_version() -> str
```

Get version from pyproject.toml

<a id="ccnget.geturl.get_parser"></a>

#### get\_parser

```python
def get_parser() -> argparse.ArgumentParser
```

Build and return the ArgumentParser for ccnget.

<a id="ccnget.geturl.main"></a>

#### main

```python
def main(argv: Optional[list[str]] = None) -> None
```

Parse CLI arguments and dispatch to subcommands.

<a id="ccnget.api"></a>

# ccnget.api

Public library API for ccnget.

Lookup and retrieve archived web pages from the Common Crawl News dataset.

Example
-------
```
>>> import ccnget
>>> result = ccnget.fetch("http://example.com")
>>> print(result.surt_key, result.timestamp)
>>> tree = LexborHTMLParser(result.payload)
```

<a id="ccnget.api.LookupEntry"></a>

## LookupEntry Objects

```python
@dataclass
class LookupEntry()
```

One CDX index hit returned by the lookup API.

<a id="ccnget.api.LookupResult"></a>

## LookupResult Objects

```python
@dataclass
class LookupResult()
```

Result of a CDX index lookup.

<a id="ccnget.api.FetchResult"></a>

## FetchResult Objects

```python
@dataclass
class FetchResult()
```

Result of fetching an archived page.

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

<a id="ccnget.api.lookup"></a>

#### lookup

```python
def lookup(url: str,
           *,
           exact: bool = False,
           limit: int = 10,
           at: str | None = None,
           cdx_url: str = CDX_LOOKUP_URL) -> LookupResult
```

Search the CC-NEWS CDX index for *url*.

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
cdx_url : str
    Override the CDX lookup endpoint.

Returns
-------
LookupResult

<a id="ccnget.api.retrieve"></a>

#### retrieve

```python
def retrieve(warc_path: str,
             offset: int,
             length: int,
             *,
             base_url: str = CC_CRAWL_BASE_URL,
             surt_key: str = "",
             timestamp: str = "") -> FetchResult
```

Retrieve a single WARC record via byte-range request.

Parameters
----------
warc_path : str
    Path within Common Crawl storage (e.g. ``crawl-data/CC-NEWS/...``).
offset : int
    Byte offset of the record.
length : int
    Byte length of the record.
base_url : str
    Override the Common Crawl base URL.
surt_key : str
    SURT key from the CDX index (populated by ``fetch()``).
timestamp : str
    Timestamp from the CDX index (populated by ``fetch()``).

Returns
-------
FetchResult

<a id="ccnget.api.fetch"></a>

#### fetch

```python
def fetch(url: str,
          *,
          exact: bool = False,
          at: str | None = None,
          cdx_url: str = CDX_LOOKUP_URL,
          base_url: str = CC_CRAWL_BASE_URL) -> FetchResult
```

Lookup *url* in the CDX index and retrieve the first archived result.

Convenience wrapper around :func:`lookup` + :func:`retrieve`.

Parameters
----------
url : str
    URL to search for.
exact : bool
    Require exact match.
at : str | None
    Timestamp filter (YYYYMMDDhhmmss).
cdx_url : str
    Override the CDX lookup endpoint.
base_url : str
    Override the Common Crawl base URL.

Returns
-------
FetchResult

<a id="ccnget.api.CcngetError"></a>

## CcngetError Objects

```python
class CcngetError(Exception)
```

Base exception for ccnget.

<a id="ccnget.api.NotFoundError"></a>

## NotFoundError Objects

```python
class NotFoundError(CcngetError)
```

Raised when a URL has no matches in the CDX index.

<a id="ccnget.api.NoRecordError"></a>

## NoRecordError Objects

```python
class NoRecordError(CcngetError)
```

Raised when a WARC segment contains no response record.

