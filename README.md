# `ccnget` -- common crawl news get

Search over 1.4 Billion archived news URLs from CC-NEWS and retrieve contents from WARC files.

`/cdx-index/lookup` Endpoint [🤗 Hugging Face Space (2023-2024)](https://huggingface.co/spaces/brian-learns/cc-news-cdx-server) | [🐳 docker compose (2016-Aug to 2026-July)](https://github.com/brian-learns/cdx_rocks) 

## Quickstart
Running the command
```bash
uvx --from git+https://github.com/brian-learns/ccnget ccnget fetch http://example.com/ | uvx trafilatura
```
will lookup `http://example.com/` in an index; get the WARC file, offset, and size; get the archived web page from S3; then extract some text with [`trafilatura`](https://github.com/adbar/trafilatura) -- resulting in:
```
This domain is for use in illustrative examples in documents. You may use this domain in literature without prior coordination or asking for permission.
More information...
```
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

The client appends `/cdx-index/lookup` and `/cdx-index/extent` to this base.
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

Lookup and retrieve the first result in one step:

```bash
uv run ccnget fetch "http://example.com" -o article.html
```

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
