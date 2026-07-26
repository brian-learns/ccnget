# `ccnget` -- common crawl news get

CLI for querying a [Common Crawl News index](https://huggingface.co/datasets/brian-learns/cdx-cc-news) and retrieving archived web pages from CC-NEWS Common Crawl WARC files.

Uses a [URL lookup tool](https://huggingface.co/spaces/brian-learns/cc-news-cdx-server) served from a HuggingFace Space that indexes the [Common Crawl News Dataset](https://data.commoncrawl.org/crawl-data/CC-NEWS/index.html) in RocksDB provides a simple FastAPI `/lookup` endpoint.

## Install

```bash
uv add git+https://github.com/brian-learns/ccnget
```

## Usage

### Lookup

Search a [CC-NEWS index](https://huggingface.co/datasets/brian-learns/cdx-cc-news) for a URL:

```bash
uv run ccnget lookup "http://www.cnn.com" --limit 5
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
uv run ccnget fetch "http://www.cnn.com" -o article.html
```

## License

BSD 3-Clause for the code in this revision control repository.

Files retrieved from Common Crawl are subject to [Common Crawl Terms of Use](https://commoncrawl.org/terms-of-use) and the original publisher's copyright.

