"""ccnget -- lookup URLs and get archived pages from Common Crawl News.

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
"""

from ccnget.api import (
    CcngetError,
    FetchResult,
    LookupEntry,
    LookupResult,
    NoRecordError,
    NotFoundError,
    fetch,
    lookup,
    retrieve,
)
from ccnget.config import (
    get_config,
    list_config,
    set_config,
    show_config_path,
    unset_config,
)

__all__ = [
    "CcngetError",
    "FetchResult",
    "LookupEntry",
    "LookupResult",
    "NoRecordError",
    "NotFoundError",
    "fetch",
    "get_config",
    "list_config",
    "lookup",
    "retrieve",
    "set_config",
    "show_config_path",
    "unset_config",
]
