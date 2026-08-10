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

Or manage persistent settings:
>>> ccnget.set_config("cdx-url", "http://localhost:8000/lookup")
>>> ccnget.get_config("cdx-url")
'http://localhost:8000/lookup'
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

<a id="ccnget.geturl.config_cmd"></a>

#### config\_cmd

```python
def config_cmd(args: argparse.Namespace) -> None
```

Execute the config subcommand (set/get/show/unset).

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

<a id="ccnget.geturl.extent_cmd"></a>

#### extent\_cmd

```python
def extent_cmd(args: argparse.Namespace) -> None
```

Execute the extent subcommand.

<a id="ccnget.geturl.main"></a>

#### main

```python
def main(argv: Optional[list[str]] = None) -> None
```

Parse CLI arguments and dispatch to subcommands.

<a id="ccnget.retry"></a>

# ccnget.retry

Retry with exponential backoff for network operations.

Retries on transient errors: connection failures, timeouts, and 5xx
responses.  Used by ``lookup()`` and ``retrieve()``.

<a id="ccnget.retry.retry_with_backoff"></a>

#### retry\_with\_backoff

```python
def retry_with_backoff(fn: Callable[..., T],
                       *,
                       max_retries: int = 3,
                       base_delay: float = 1.0,
                       max_delay: float = 30.0,
                       jitter: float = 0.2) -> T
```

Call *fn* with exponential backoff on transient failures.

Retries on connection errors, timeouts, and 5xx HTTP responses.

Parameters
----------
fn : callable
    The function to call.  Must return a ``requests.Response``.
max_retries : int
    Maximum number of retries (not counting the initial attempt).
base_delay : float
    Initial delay in seconds between retries.
max_delay : float
    Upper bound on the delay between retries.
jitter : float
    Fraction of random jitter added to each delay (0-1).

Returns
-------
T
    The response returned by *fn*.

Raises
------
requests.exceptions.RequestException
    The last exception after all retries are exhausted.
requests.exceptions.HTTPError
    Raised by ``response.raise_for_status()`` for non-retryable
    HTTP errors (4xx).

<a id="ccnget.config"></a>

# ccnget.config

Persistent configuration management for ccnget.

Reads/writes a JSON file under the user config directory
(platformdirs: ~/.config/ccnget/config.json on Linux).

Resolution chain (highest priority first):
    1. CLI flag / function argument (explicit override)
    2. Config file (set via ``ccnget config set``)
    3. Environment variable
    4. Hard-coded default

<a id="ccnget.config.get_config"></a>

#### get\_config

```python
def get_config(key: str) -> str | None
```

Return the value for *key* from the config file, or ``None`` if not set.

<a id="ccnget.config.set_config"></a>

#### set\_config

```python
def set_config(key: str, value: str) -> None
```

Persist *value* for *key* in the config file.

<a id="ccnget.config.unset_config"></a>

#### unset\_config

```python
def unset_config(key: str) -> None
```

Remove *key* from the config file.

<a id="ccnget.config.list_config"></a>

#### list\_config

```python
def list_config() -> dict[str, dict[str, str | None]]
```

Return all config keys with their resolved values and sources.

<a id="ccnget.config.show_config_path"></a>

#### show\_config\_path

```python
def show_config_path() -> str
```

Return the path to the config file.

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

<a id="ccnget.api.ExtentResult"></a>

## ExtentResult Objects

```python
@dataclass
class ExtentResult()
```

Result of querying the extent endpoint.

Attributes
----------
file_extent : int
    Number of files covered by this index.
file_oldest : str
    First WARC file in this index.
file_newest : str
    Last WARC file added to this index.

<a id="ccnget.api.lookup"></a>

#### lookup

```python
def lookup(url: str,
           *,
           exact: bool = False,
           limit: int = 10,
           at: str | None = None,
           cdx_url: str | None = None) -> LookupResult
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
cdx_url : str | None
    Override the CDX lookup endpoint. Falls back to config file,
    then environment variable ``CDX_LOOKUP_URL``, then hard-coded default.

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
             base_url: str | None = None,
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

<a id="ccnget.api.fetch"></a>

#### fetch

```python
def fetch(url: str,
          *,
          exact: bool = False,
          at: str | None = None,
          cdx_url: str | None = None,
          base_url: str | None = None) -> FetchResult
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
cdx_url : str | None
    Override the CDX lookup endpoint. Falls back to config file,
    then environment variable ``CDX_LOOKUP_URL``, then hard-coded default.
base_url : str | None
    Override the Common Crawl base URL. Falls back to config file,
    then environment variable ``CC_CRAWL_BASE_URL``, then hard-coded default.

Returns
-------
FetchResult

<a id="ccnget.api.extent"></a>

#### extent

```python
def extent(*, cdx_url: str | None = None) -> ExtentResult
```

Query the extent endpoint for index statistics.

Parameters
----------
cdx_url : str | None
    Override the CDX lookup endpoint. The ``/extent`` path is derived
    by replacing the last path segment (e.g. ``/lookup`` → ``/extent``).
    Falls back to config file, then environment variable ``CDX_LOOKUP_URL``,
    then hard-coded default.

Returns
-------
ExtentResult

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

