"""Headlines: general market news from FT, NYT and WSJ.

WSJ's own RSS feeds stopped updating in January 2025, so WSJ comes from Google
News searches restricted to wsj.com's finance and economy sections.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)


def _google_news(query: str) -> str:
    return "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})


FEEDS: list[tuple[str, str]] = [
    ("FT", "https://www.ft.com/markets?format=rss"),
    ("NYT", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    ("NYT", "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"),
    ("WSJ", _google_news("site:wsj.com/finance when:1d")),
    ("WSJ", _google_news("site:wsj.com/economy when:1d")),
]
LIMIT = 15
PER_SOURCE = 6  # Google News returns ~100 WSJ items a day; keep the mix
# Word-set Jaccard at or above which two titles are the same story. Duplicates here are
# mostly one article listed twice (NYT Business and Economy, Google News variants);
# lower thresholds merge different stories like "Oil prices rise..." / "Gold prices rise...".
SIMILAR = 0.8
TIMEOUT = 8

_SOURCE_SUFFIX = re.compile(r"\s+[-|–]\s+(WSJ|The Wall Street Journal|Financial Times|FT|The New York Times)$")
_FILLER = {"here's the latest.", "here’s the latest.", "live updates", "the latest"}
_STOP = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "at", "by", "with", "as",
    "is", "are", "was", "be", "it", "its", "from", "that", "this", "after", "over", "into",
    "how", "why", "what", "says", "say", "s",
}


@dataclass
class Headline:
    title: str
    url: str
    published: datetime
    sources: list[str] = field(default_factory=list)
    words: frozenset[str] = frozenset()

    def to_json(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "published": self.published.isoformat(),
            "sources": self.sources,
        }


def clean_title(title: str) -> str:
    title = " ".join(unescape(title).split())
    return _SOURCE_SUFFIX.sub("", title)


def title_words(title: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z0-9]+", title.lower().replace("’", "'").replace("'", ""))
    return frozenset(t for t in tokens if t not in _STOP and len(t) > 1)


def is_filler(title: str) -> bool:
    """Live-blog stubs, opinion columns and automated wire roundups aren't market news."""
    lower = title.lower()
    return (
        lower in _FILLER
        or len(title.split()) < 4
        or lower.startswith(("opinion |", "opinion:"))
        or "market talk" in lower
    )


def parse_feed(source: str, xml: bytes) -> list[Headline]:
    root = ET.fromstring(xml)
    out = []
    for item in root.iter("item"):
        title = clean_title(item.findtext("title") or "")
        url = (item.findtext("link") or "").strip()
        when = (item.findtext("pubDate") or "").strip()
        if not title or not url or not when or is_filler(title):
            continue
        try:
            published = parsedate_to_datetime(when)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        out.append(Headline(title, url, published.astimezone(timezone.utc), [source], title_words(title)))
    return out


def similar(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= SIMILAR


def merge(items: list[Headline], limit: int = LIMIT, per_source: int = PER_SOURCE) -> list[Headline]:
    """Newest first; a story carried by several sources appears once, tagged with each."""
    kept: list[Headline] = []
    for item in sorted(items, key=lambda h: h.published, reverse=True):
        twin = next((k for k in kept if k.url == item.url or similar(k.words, item.words)), None)
        if twin is not None:
            for s in item.sources:
                if s not in twin.sources:
                    twin.sources.append(s)
            continue
        kept.append(item)

    counts: dict[str, int] = {}
    out = []
    for h in kept:
        primary = h.sources[0]
        if counts.get(primary, 0) >= per_source:
            continue
        counts[primary] = counts.get(primary, 0) + 1
        out.append(h)
        if len(out) == limit:
            break
    return out


def _fetch(feed: tuple[str, str]) -> list[Headline]:
    source, url = feed
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return parse_feed(source, r.content)


def fetch() -> tuple[list[Headline], list[str]]:
    """All feeds in parallel. Returns the merged headlines and the feeds that failed."""
    items: list[Headline] = []
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        for feed, fut in zip(FEEDS, [pool.submit(_fetch, f) for f in FEEDS]):
            try:
                items.extend(fut.result())
            except Exception as e:
                failed.append(feed[1])
                log.warning("feed %s failed: %s", feed[1], e)
    return merge(items), failed
