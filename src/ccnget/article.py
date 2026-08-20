"""Article extraction for ccnget: YAML frontmatter + markdown.

Turns a retrieved WARC payload into a clean article: trafilatura
extraction with a 3-level auto-fallback (full metadata -> text-only ->
raw HTML strip), language detection, and a metadata dict rendered as
YAML frontmatter ahead of a markdown body.

This backs the ``ccnget fetch`` default human/agent output. The raw
bytes remain available via :func:`ccnget.api.fetch` / ``ccnget fetch
--raw``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import trafilatura
from iso639 import Lang
from langdetect import LangDetectException, detect

from ccnget.api import fetch as api_fetch

logger: logging.Logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH: int = 20
RAW_STRIP_MAX_CHARS: int = 40000
BRIEF_MAX_CHARS: int = 500


@dataclass
class ArticleResult:
    """An archived article after extraction.

    Attributes
    ----------
    url : str
        The URL that was requested.
    payload : bytes
        Raw retrieved bytes (WARC response body, typically HTML).
    http_headers : dict[str, str]
        HTTP headers from inside the WARC record.
    warc_headers : dict[str, str]
        WARC record headers.
    surt_key : str
        SURT key from the CDX index.
    timestamp : str
        WARC timestamp (YYYYMMDDhhmmss).
    warc_path : str
        Path of the WARC file on Common Crawl storage.
    metadata : dict[str, Any]
        Extracted metadata (title, author, date, language, ...).
    body : str
        Markdown body (full article).
    fallback_level : int
        1 = full trafilatura metadata, 2 = text-only, 3 = raw HTML strip.
    """

    url: str
    payload: bytes
    http_headers: dict[str, str]
    warc_headers: dict[str, str]
    surt_key: str
    timestamp: str
    warc_path: str
    metadata: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    fallback_level: int = 1


# ── Helpers ───────────────────────────────────────────────────────────────


def _format_timestamp(ts: str) -> str:
    """Convert a CDX timestamp YYYYMMDDhhmmss to an ISO date (YYYY-MM-DD)."""
    if not ts or len(ts) < 8:
        return ts
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


def _detect_language(text: str) -> Optional[str]:
    """Detect the language of *text* and return its full name, else None."""
    try:
        if text and len(text) > 50:
            return Lang(detect(text)).name
    except (LangDetectException, ValueError):
        return None
    return None


def _title_from_url(url: str) -> str:
    """Derive a best-effort title from the URL path (fallback levels 2-3)."""
    try:
        path_parts = urlparse(url).path.strip("/").split("/")
        if not path_parts:
            return ""
        title_text = path_parts[-1]
        title_text = re.sub(r"\.(html|htm|php|asp)$", "", title_text)
        title_text = re.sub(r"[-_]+", " ", title_text).title()
        return title_text
    except Exception:
        return ""


def _extract_metadata(doc, url: str, timestamp: str, fallback_level: int) -> dict[str, Any]:
    """Build a metadata dict from a trafilatura Document."""
    meta: dict[str, Any] = {"url": url, "date": _format_timestamp(timestamp)}
    if doc:
        if doc.title:
            meta["title"] = doc.title
        if doc.author:
            meta["author"] = doc.author
        if doc.date:
            meta["date"] = doc.date
        if doc.language:
            meta["language"] = doc.language
        elif doc.text:
            meta["language"] = _detect_language(doc.text)
        if doc.hostname:
            meta["hostname"] = doc.hostname
        if doc.sitename:
            meta["sitename"] = doc.sitename
        if doc.description:
            meta["description"] = doc.description
        if doc.categories:
            meta["categories"] = doc.categories
        if doc.tags:
            meta["tags"] = doc.tags
    return meta


def _yaml_meta(meta: dict[str, Any], fields: Optional[list[str]] = None) -> str:
    """Render *meta* as a YAML frontmatter block.

    When *fields* is given, only those keys are included.
    """
    lines = ["---"]
    for key, value in meta.items():
        if fields is not None and key not in fields:
            continue
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
        elif isinstance(value, str) and "\n" in value:
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _strip_html_tags(html_text: str, max_chars: int = RAW_STRIP_MAX_CHARS) -> str:
    """Crude HTML tag stripping for the level-3 fallback."""
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _split_frontmatter(text: str) -> str:
    """Strip trafilatura's own YAML frontmatter, returning the body only."""
    parts = text.split("---\n", 2)
    if len(parts) >= 3:
        return parts[2]
    return text


def _get_first_paragraph(text: str, max_chars: int = BRIEF_MAX_CHARS) -> str:
    """Extract the first meaningful paragraph from markdown *text*."""
    lines = text.split("\n")
    content_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        content_lines.append(line)
    content = "\n".join(content_lines).strip()

    if "\n\n" in content:
        paragraphs = content.split("\n\n")
        for para in paragraphs:
            para_stripped = para.strip()
            if len(para_stripped) > 30 and not (
                len(para_stripped) < 100
                and " \u2014" in para_stripped
                and ". " not in para_stripped.replace(" \u2014", "")
            ):
                return para_stripped[:max_chars]
        first_para = paragraphs[0].strip()
    else:
        first_para = content.split("\n")[0]

    return first_para[:max_chars]


def _dedupe_paragraphs(text: str) -> str:
    """Drop duplicated paragraphs (common in stripped-HTML fallbacks)."""
    seen: set[str] = set()
    deduped: list[str] = []
    for p in text.split("\n\n"):
        p_stripped = p.strip()
        if p_stripped and p_stripped not in seen:
            deduped.append(p)
            seen.add(p_stripped)
    return "\n\n".join(deduped).strip()


# ── Extraction levels ─────────────────────────────────────────────────────


def _apply_target_uri(meta: dict[str, Any], warc_headers: dict[str, str]) -> None:
    """Prefer the WARC-Target-URI (the original crawled URL) over the requested one.

    The CDX SURT key is a lossy transform (redirects, trailing slashes, and
    scheme are not preserved), so the WARC record header is the authoritative
    source for the original URL.
    """
    target = warc_headers.get("WARC-Target-URI")
    if target:
        meta["url"] = target


def _extract_level_1(payload: bytes, url: str):
    """Level 1: full trafilatura extraction with metadata (Document or None)."""
    try:
        doc = trafilatura.extract_with_metadata(
            filecontent=payload,
            include_links=True,
            deduplicate=True,
            include_images=True,
            url=url,
            include_formatting=True,
            date_extraction_params={"extensive_search": True},
        )
        if doc and doc.text and len(doc.text.strip()) > MIN_TEXT_LENGTH:
            return doc
    except Exception:
        logger.debug("Level-1 extraction failed", exc_info=True)
    return None


def _extract_level_2(payload: bytes) -> Optional[str]:
    """Level 2: text-only trafilatura extraction."""
    try:
        text = trafilatura.extract(payload)
        if text and len(text.strip()) > MIN_TEXT_LENGTH:
            return text
    except Exception:
        logger.debug("Level-2 extraction failed", exc_info=True)
    return None


def _extract_level_3(payload: bytes) -> Optional[str]:
    """Level 3: raw HTML tag stripping."""
    try:
        html = payload.decode("utf-8", errors="replace")
        text = _strip_html_tags(html)
        if text and len(text) > MIN_TEXT_LENGTH:
            return text
    except Exception:
        logger.debug("Level-3 extraction failed", exc_info=True)
    return None


# ── Public API ────────────────────────────────────────────────────────────


def extract(
    payload: bytes,
    *,
    url: str,
    timestamp: str = "",
    warc_path: str = "",
    surt_key: str = "",
    http_headers: dict[str, str] | None = None,
    warc_headers: dict[str, str] | None = None,
) -> ArticleResult:
    """Run the 3-level extraction fallback over a retrieved WARC payload.

    This is the core behind :func:`article` and the TUI Reader. It takes an
    already-retrieved payload so callers can pick a *specific* capture (from a
    scan/lookup row) rather than letting :func:`api_fetch` re-resolve the
    first result for a URL.

    Parameters
    ----------
    payload : bytes
        Raw WARC response body (typically HTML).
    url : str
        URL that was requested / that the capture belongs to.
    timestamp : str
        WARC timestamp (YYYYMMDDhhmmss) from the CDX index.
    warc_path : str
        Path of the WARC file (from the CDX index).
    surt_key : str
        SURT key from the CDX index.
    http_headers : dict[str, str] | None
        HTTP headers from inside the WARC record (if available).
    warc_headers : dict[str, str] | None
        WARC record headers. ``WARC-Target-URI`` (the original crawled URL)
        is preferred over *url* in the resulting metadata.

    Returns
    -------
    ArticleResult
    """
    http_headers = http_headers or {}
    warc_headers = warc_headers or {}

    doc = _extract_level_1(payload, url)
    if doc is not None:
        meta = _extract_metadata(doc, url, timestamp, 1)
        _apply_target_uri(meta, warc_headers)
        return ArticleResult(
            url=url,
            payload=payload,
            http_headers=http_headers,
            warc_headers=warc_headers,
            surt_key=surt_key,
            timestamp=timestamp,
            warc_path=warc_path,
            metadata=meta,
            body=_split_frontmatter(doc.text) if doc.text else "",
            fallback_level=1,
        )

    text = _extract_level_2(payload)
    if text is not None:
        meta = {"url": url, "date": _format_timestamp(timestamp)}
        title = _title_from_url(url)
        if title:
            meta["title"] = title
        language = _detect_language(text)
        if language:
            meta["language"] = language
        _apply_target_uri(meta, warc_headers)
        return ArticleResult(
            url=url,
            payload=payload,
            http_headers=http_headers,
            warc_headers=warc_headers,
            surt_key=surt_key,
            timestamp=timestamp,
            warc_path=warc_path,
            metadata=meta,
            body=_dedupe_paragraphs(text),
            fallback_level=2,
        )

    raw_text = _extract_level_3(payload)
    if raw_text is not None:
        meta = {"url": url, "date": _format_timestamp(timestamp)}
        title = _title_from_url(url)
        if title:
            meta["title"] = title
        language = _detect_language(raw_text)
        if language:
            meta["language"] = language
        _apply_target_uri(meta, warc_headers)
        return ArticleResult(
            url=url,
            payload=payload,
            http_headers=http_headers,
            warc_headers=warc_headers,
            surt_key=surt_key,
            timestamp=timestamp,
            warc_path=warc_path,
            metadata=meta,
            body=_dedupe_paragraphs(raw_text),
            fallback_level=3,
        )

    # Nothing extractable: return the raw payload with empty body so the
    # caller can still hand back the bytes (fetch --raw) or report a clear
    # error for text formats.
    meta = {"url": url, "date": _format_timestamp(timestamp)}
    _apply_target_uri(meta, warc_headers)
    return ArticleResult(
        url=url,
        payload=payload,
        http_headers=http_headers,
        warc_headers=warc_headers,
        surt_key=surt_key,
        timestamp=timestamp,
        warc_path=warc_path,
        metadata=meta,
        body="",
        fallback_level=0,
    )


def article(
    url: str,
    *,
    exact: bool = False,
    at: str | None = None,
    cdx_url: str | None = None,
    base_url: str | None = None,
) -> ArticleResult:
    """Lookup *url* in the CDX index, retrieve the first archived result,
    and extract it as an article (metadata + markdown body).

    Falls back through three extraction levels automatically; the level
    used is reported in :attr:`ArticleResult.fallback_level`.

    Parameters
    ----------
    url : str
        URL to search for.
    exact : bool
        Require an exact index match.
    at : str | None
        Timestamp filter (YYYYMMDDhhmmss).
    cdx_url : str | None
        Override the CDX server base URL (config > env > default).
    base_url : str | None
        Override the Common Crawl base URL (config > env > default).

    Returns
    -------
    ArticleResult
    """
    result = api_fetch(url, exact=exact, at=at, cdx_url=cdx_url, base_url=base_url)
    return extract(
        result.payload,
        url=url,
        timestamp=result.timestamp,
        warc_path=result.warc_path,
        surt_key=result.surt_key,
        http_headers=result.http_headers,
        warc_headers=result.warc_headers,
    )


def article_to_dict(res: ArticleResult, *, mode: str = "full") -> dict[str, Any]:
    """The canonical JSON shape for an article.

    ``--select`` dot-paths address this structure: ``metadata.title``,
    ``metadata``, ``body``, ``fallback_level``, ...
    """
    body = _get_first_paragraph(res.body) if mode == "brief" else res.body
    return {
        "url": res.url,
        "surt_key": res.surt_key,
        "timestamp": res.timestamp,
        "warc_path": res.warc_path,
        "fallback_level": res.fallback_level,
        "metadata": res.metadata,
        "body": body,
    }


def article_to_text(
    res: ArticleResult,
    *,
    mode: str = "full",
    quiet: bool = False,
    fields: Optional[list[str]] = None,
) -> str:
    """Render an article as YAML frontmatter + markdown body.

    ``quiet`` emits only the frontmatter; ``fields`` restricts the
    frontmatter keys (e.g. a compact high-gravity subset).
    """
    if quiet:
        return _yaml_meta(res.metadata, fields)
    body = _get_first_paragraph(res.body) if mode == "brief" else res.body
    return f"{_yaml_meta(res.metadata)}\n\n{body}"
