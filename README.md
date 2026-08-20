# `ccnget` -- common crawl news get

Search over 1.4 Billion archived news URLs from CC-NEWS and retrieve contents from WARC files.

`/cdx-index/lookup` Endpoint [🤗 Hugging Face Space (2023-2024)](https://huggingface.co/spaces/brian-learns/cc-news-cdx-server) | [🐳 docker compose (2016-Aug to 2026-July)](https://github.com/brian-learns/cdx_rocks) 

## Quickstart
Running the command
```bash
uvx --from git+https://github.com/brian-learns/ccnget ccnget fetch http://example.com/
```
will lookup `http://example.com/` in an index; get the WARC file, offset, and size; get the archived web page from S3; then extract the article with [`trafilatura`](https://github.com/adbar/trafilatura) and print it as **YAML frontmatter + markdown** -- resulting in:
```
---
url: http://example.com/
date: 2024-06-30
title: Example Domain
language: English
hostname: example.com
---
This domain is for use in illustrative examples in documents. You may use this domain in literature without prior coordination or asking for permission.
More information...
```
Add `--json` for structured output, `--select body` for markdown only, or `--raw` for the raw HTML bytes. See [Output Modes](#output-modes) and [Fetch](#fetch) for the full set.

Or use as a library, as [demonstrated in this google colab](https://colab.research.google.com/drive/1DiZBPQGjcyudrpCIhh1goaFVpOvmVp6d?usp=sharing)

## Background

[Common Crawl Announced a News Dataset](https://commoncrawl.org/blog/news-dataset-available) October 4th, 2016, "containing news articles from news sites all over the world."  Between then end of June 2016 over 1.4 billion news articles have been archived in the set.

This repository contains a python command for looking up and retrieving URLs from the [WARC files on S3](https://data.commoncrawl.org/crawl-data/CC-NEWS/index.html).

[`webrecorder/cdxj-indexer`](https://github.com/webrecorder/cdxj-indexer) was used to create a [Hugging Face Dataset `brian-learns/cdx-cc-news`](https://huggingface.co/datasets/brian-learns/cdx-cc-news) with CDXj sorted by month and parquet files.  Rocks DB was used to create a bloom filter index that powers a [URL lookup tool](https://huggingface.co/spaces/brian-learns/cc-news-cdx-server) served from a HuggingFace Space that provides a simple FastAPI `/cdx-index/lookup` endpoint.

## Install

```bash
uv add git+https://github.com/brian-learns/ccnget
```

## Usage

see also:
```
uv run ccnget --help
```

### Config

Set a persistent lookup server base URL (stored in user config directory):

```bash
uv run ccnget config set cdx-url http://localhost:8000
uv run ccnget config show
uv run ccnget config get cdx-url
uv run ccnget config unset cdx-url
```

The client appends `/cdx-index/lookup`, `/cdx-index/extent`,
`/cdx-index/surt-browse`, and `/cdx-index/surt-prefix` to this base.
Old values ending in `/lookup` or `/cdx-index/lookup` are still accepted
(the endpoint suffix is trimmed).

Settings are resolved in this order (highest priority first):

1. **Config file** (set via `ccnget config set`)
2. **Environment variable** (`CDX_URL`, `CC_CRAWL_BASE_URL`)
3. **Hard-coded default**

### Lookup

Search a [CC-NEWS index](https://huggingface.co/datasets/brian-learns/cdx-cc-news) for a URL:

```bash
uv run ccnget lookup "http://example.com" --limit 5
```

### Retrieve

Download a specific WARC record by offset and length:

```bash
uv run ccnget retrieve \
  --warc-path "crawl-data/CC-NEWS/2017/01/CC-NEWS-20170101071327-00034.warc.gz" \
  --offset 696229346 \
  --length 29897
```

Save to file instead of stdout:

```bash
uv run ccnget retrieve \
  --warc-path "crawl-data/CC-NEWS/2017/01/CC-NEWS-20170101071327-00034.warc.gz" \
  --offset 696229346 \
  --length 29897 \
  -o article.html
```

### Fetch

Lookup and fetch the first archived result in one step. By default the
page is extracted with trafilatura (with an automatic 3-level fallback)
and printed as **YAML frontmatter + markdown** — the human default:

```bash
uv run ccnget fetch "http://example.com"
```

```
---
url: http://example.com/
date: 2024-06-30
title: Example Domain
language: English
hostname: example.com
---
This domain is for use in illustrative examples in documents...
```

Pipe it straight to a file: `uv run ccnget fetch URL > article.md`.

Agent / machine options:

```bash
uv run ccnget fetch URL --json                        # structured JSON (metadata + body)
uv run ccnget fetch URL --compact                     # minified single-line JSON
uv run ccnget fetch URL --select metadata.title       # pluck one field
uv run ccnget fetch URL --select metadata             # whole metadata object
uv run ccnget fetch URL --select body                 # markdown body only
uv run ccnget fetch URL --quiet                       # metadata only, no body
uv run ccnget fetch URL --mode brief                  # first paragraph only
uv run ccnget fetch URL --raw                         # raw payload bytes (previous default)
uv run ccnget fetch URL --raw -o page.html            # raw bytes to a file
```

`--select` uses the same dot-notation as the other subcommands and
addresses the JSON shape: `url`, `surt_key`, `timestamp`, `warc_path`,
`fallback_level`, `metadata.*`, `body`. `--raw` writes raw bytes and
ignores the other output flags. When nothing readable can be extracted,
the command exits 5 and points you at `--raw`.

### Extent

Show what content is indexed on the server:

```bash
uv run ccnget extent
```

### Surt Browse

Browse the hosts indexed on the server, one level of the SURT tree at a
time. Start at the root level, then descend using any child pattern from
the result:

```bash
uv run ccnget surt-browse                 # root level, 50 children
uv run ccnget surt-browse com,aa          # one level down
uv run ccnget surt-browse com,aa --limit 200 --offset 50
```

`next_offset` in the output is the `--offset` for the next page (null on
the last page).

### Surt Prefix

Prefix search: find capture records under a SURT prefix, e.g.
`com,aa` (host + subdomains) or `com,aaa,ace)/activities` (path prefix of
ace.aaa.com):

```bash
uv run ccnget surt-prefix com,aa --limit 20
```

### TUI

A terminal UI (built with [Textual](https://textual.textualize.io/)) with
three tabs: **Browse** (walk the SURT host tree), **Scan** (prefix search
over capture records), and **Reader** (extracted article: metadata +
markdown). It requires the optional `tui` extra:

```bash
uv add "ccnget[tui]"
uv run ccnget tui
```

Inside the TUI: `1`/`2`/`3` switch tabs, `enter` drills into a Browse row
/ runs a Scan / fetches the selected Scan row into the Reader, `c` on a
Browse row jumps to Scan with that pattern, `q` quits. The Reader also has
a URL field for fetching any archived URL directly. The index base URL
is resolved from config / `CDX_URL` / default (see [Config](#config)) and
shown read-only in the header; if the server is unreachable at startup
the TUI prints the error and exits 5.

### Output Modes

The JSON-producing subcommands (`lookup`, `extent`, `surt-browse`,
`surt-prefix`) pick their output format automatically: an interactive
terminal gets a colored table, and piped output gets pretty JSON. All of
it can be overridden per command:

```bash
uv run ccnget lookup "http://example.com" --json        # pretty JSON
uv run ccnget lookup "http://example.com" --compact     # minified one-line JSON
uv run ccnget extent --table                            # force the table view
```

`--select` plucks a single value out of the result with dot notation and
prints it raw (no envelope, no table) — handy for agents and shell
pipelines:

```bash
uv run ccnget lookup "http://example.com" --select results.0.warc_path
uv run ccnget surt-prefix com,aa --select results.warc_path   # maps over the list
uv run ccnget extent --select file_extent
```

A bare name addresses a top-level field; `results.0.field` indexes a
specific entry; a bare field name after a list maps over every entry and
returns a JSON array.

`fetch` writes the extracted article (or `--raw` bytes) to stdout or
`-o FILE`.

### Exit Codes

Commands exit with typed codes so scripts and agents can branch on them:

| Code | Meaning |
|------|---------|
| 0 | success (an empty result set is success) |
| 2 | usage error (bad flags, bad `--select` path) |
| 3 | not found (no index match) |
| 5 | API error (network failure or server error) |

(`ccnget tui` exits 0 on a clean quit and 5 when the server is
unreachable at startup.)

In `--json`/`--compact`/`--select` context, errors are reported as a
single-line JSON object on stderr: `{"status":"error","code":5,"error":"..."}`.

## Environment

 * **`CDX_URL`** The base URL for the CDX index server.
   * Default: *`https://brian-learns-cc-news-cdx-server.hf.space/`*
 * **`CC_CRAWL_BASE_URL`** The base URL for downloading Common Crawl data.
   * Default: *`https://data.commoncrawl.org`*

These variables can be set directly in your shell environment or defined
in a local *.env* file.

## Diagram

While most of this was vibe coded, I drew this architecture diagram in monodraw and came up with the basic approach.  Numbers are as of the first test retrospective build.  I'm not sure if I'm going to do prospective maintenance.
```
 ┌────────────────────────────────────────┐       
 │  s3://commoncrawl/crawl-data/CC-NEWS/  │       
 │           49.4 TiB raw WARC            │       
 └───────────────┬────────────────────┬▲──┘       
  streamed WARC  │                    ││          
      files      │                    ││          
                 ▼                    ││          
 ┌────────────────────────────────┐   ││          
 │Huggingface Dataset             │   ││          
 │ - cdxj file per month          │   ││          
 │ - 115 GB, 119 files            │   ││          
 └───────────────┬────────────────┘   ││  range   
                 │                    ││ request  
                 │                    ││          
                 ▼                    ││          
 ┌────────────────────────────────┐   ││          
 │Huggingface Space               │   ││          
 │ - rocksdb (75.1 GB, 1116 files)│   ││          
 │ - fastapi /cdx-index/lookup?   │   ││          
 └────┬▲──────────────────────────┘   ││          
      ││                              ││          
      ││                              ││          
      ▼│                              ▼│          
 ┌────────────────────────────────────────┐       
 │                 ccnget                 │       
 │   lookup                    retrieve   │       
 └────────────────────────────────────────┘       
```

## Supporting Code
Besides the code in this repository, code needed to make this work is in 
 * [`brian-learns/cdx-cc-news` dataset Files tab](https://huggingface.co/datasets/brian-learns/cdx-cc-news/tree/main) to build cdxj and rocksdb indexes
 * [`brian-learns/cc-news-cdx-server` hf spaces Files tab](https://huggingface.co/spaces/brian-learns/cc-news-cdx-server/tree/main) for the lookup endpoint
 * NEW [`brian-learns/cdx_rocks` github](https://github.com/brian-learns/cdx_rocks) docker compose for lookup endpoint
   
## See Also
 * [`samples`](./samples/) directory with example using `duckdb` to query the parquet files, and sort of random samples of the data
 * [`man`](./man/) man page for the command line
 * [`api.md`](./api.md) pydoc markdown for use as a python module

## License

BSD 3-Clause for the code in this revision control repository.

Files retrieved from Common Crawl are subject to [Common Crawl Terms of Use](https://commoncrawl.org/terms-of-use) and the original publisher's copyright.
