# `ccnget` -- common crawl news get

[Common Crawl Announced a News Dataset](https://commoncrawl.org/blog/news-dataset-available) October 4th, 2016, "containing news articles from news sites all over the world."  Between then end of June 2016 over 1.4 billion news articles have been archived in the set.

This repository contains a python command for looking up and retrieving URLs from the [WARC files on S3](https://data.commoncrawl.org/crawl-data/CC-NEWS/index.html).

[`webrecorder/cdxj-indexer`](https://github.com/webrecorder/cdxj-indexer) was used to create a [Hugging Face Dataset `brian-learns/cdx-cc-news`](https://huggingface.co/datasets/brian-learns/cdx-cc-news) with CDXj sorted by month and parquet files.  Rocks DB was used to create a bloom filter index that powers a [URL lookup tool](https://huggingface.co/spaces/brian-learns/cc-news-cdx-server) served from a HuggingFace Space that provides a simple FastAPI `/lookup` endpoint.

## Install

```bash
uv add git+https://github.com/brian-learns/ccnget
```

## Usage

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
 │ - fastapi /lookup?             │   ││          
 └────┬▲──────────────────────────┘   ││          
      ││                              ││          
      ││                              ││          
      ▼│                              ▼│          
 ┌────────────────────────────────────────┐       
 │                 ccnget                 │       
 │   lookup                    retrieve   │       
 └────────────────────────────────────────┘       
```

Besides the code in this repository, the code to build cdxj and rocksdb indexes is in the [`brian-learns/cdx-cc-news` dataset Files tab](https://huggingface.co/datasets/brian-learns/cdx-cc-news/tree/main) and the code for the endpoint is in [`brian-learns/cc-news-cdx-server` hf spaces Files tab](https://huggingface.co/spaces/brian-learns/cc-news-cdx-server/tree/main).

## License

BSD 3-Clause for the code in this revision control repository.

Files retrieved from Common Crawl are subject to [Common Crawl Terms of Use](https://commoncrawl.org/terms-of-use) and the original publisher's copyright.

