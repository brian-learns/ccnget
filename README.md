# ccnget

CLI for querying a [Common Crawl News index](https://huggingface.co/datasets/brian-learns/cdx-cc-news) and retrieving archived web pages from CC-NEWS Common Crawl WARC files.

## Install

```bash
uv sync
```

## Usage

### Lookup

Search a [CC-NEWS index](https://huggingface.co/datasets/brian-learns/cdx-cc-news) for a URL:

```bash
ccnget lookup "http://www.cnn.com" --limit 5
```

### Retrieve

Download a specific WARC record by offset and length:

```bash
ccnget retrieve \
  --warc-path "crawl-data/CC-NEWS/2017/01/CC-NEWS-20170101071327-00034.warc.gz" \
  --offset 696229346 \
  --length 29897
```

Save to file instead of stdout:

```bash
ccnget retrieve \
  --warc-path "crawl-data/CC-NEWS/2017/01/CC-NEWS-20170101071327-00034.warc.gz" \
  --offset 696229346 \
  --length 29897 \
  -o article.html
```

### Fetch

Lookup and retrieve the first result in one step:

```bash
ccnget fetch "http://www.cnn.com" -o article.html
```

## License

BSD 3-Clause
