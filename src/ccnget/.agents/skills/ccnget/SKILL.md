---
name: ccnget
description: Look up URLs in the Common Crawl News index (over 1.4 billion archived news pages) and retrieve the archived content, extracted to markdown with metadata. Use when asked to fetch, restore, or investigate an archived copy of a web page, or to search the Common Crawl News index.
---

# ccnget

Lookup archived news URLs in the CC-NEWS CDX index and retrieve the
archived page. For one-step "get me this page" use `fetch`; use the
lower-level commands to inspect the index or pull raw bytes.

## CLI

```
ccnget fetch "URL" [--exact] [--at YYYYMMDDhhmmss] [--mode full|brief]
                   [--quiet] [--raw] [-o FILE] [output flags]
ccnget lookup "URL" [--exact] [--at TS] [--limit N] [output flags]
ccnget retrieve --warc-path P --offset N --length N [-o FILE]
ccnget extent [output flags]
ccnget surt-browse [PATTERN] [--limit N] [--offset N] [output flags]
ccnget surt-prefix PREFIX [--limit N] [output flags]
ccnget config set|get|show|unset cdx-url|cc-crawl-base-url
```

- `fetch` default: extracted article as YAML frontmatter + markdown.
  `--json` for structured output, `--raw` for the raw HTML bytes.
- `lookup` returns capture entries (surt_key, timestamp, warc_path,
  offset, length); feed them to `retrieve`.
- `surt-browse` walks the index host tree one level at a time
  (`next_offset` is the `--offset` for the next page). `surt-prefix`
  scans captures under a SURT prefix, e.g. `com,example)/`.

Output flags: `--json`, `--compact`, `--table`, `--select PATH`.
TTY default is a Rich table; piped default is pretty JSON. For
scripts/agents use `--select` (dot notation, raw output, no envelope):

```
ccnget fetch "URL" --select body                  extracted markdown
ccnget fetch "URL" --select metadata.title        one metadata field
ccnget lookup "URL" --select results.0.warc_path  first capture
ccnget lookup "URL" --select results.warc_path    all, as a JSON array
```

`fetch --json` shape: `{url, surt_key, timestamp, warc_path,
fallback_level, metadata, body}`.

Exit codes: 0 ok, 2 usage error, 3 not found (no index match), 5 API
error. In `--json/--compact/--select` mode errors are one-line JSON on
stderr: `{"status":"error","code":5,"error":"..."}`

## Python API

```python
import ccnget

result = ccnget.fetch("http://example.com")      # FetchResult
print(result.surt_key, result.timestamp, len(result.payload))

lr = ccnget.lookup("http://example.com", limit=5)
for entry in lr.entries:
    ccnget.retrieve(entry.warc_path, entry.offset, entry.length)
```

## Index and data URLs

Resolution: config file > env var > hard-coded default (the Python API
also takes `cdx_url` / `base_url` overrides).

- `cdx-url` (env `CDX_URL`) — CDX index server, default
  `https://brian-learns-cc-news-cdx-server.hf.space/`
- `cc-crawl-base-url` (env `CC_CRAWL_BASE_URL`) — WARC data bucket,
  default `https://data.commoncrawl.org`
