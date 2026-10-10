from datetime import datetime, timedelta, timezone

from app import headlines
from app.headlines import Headline, merge, parse_feed, title_words

FT = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Markets</title>
<item><title><![CDATA[Investors look to shelter portfolios from rising AI concentration risks]]></title>
<link>https://www.ft.com/content/1</link><pubDate>Sun, 04 Oct 2026 12:00:08 GMT</pubDate></item>
<item><title>Markets</title><link>https://www.ft.com/content/2</link><pubDate>Sun, 04 Oct 2026 11:00:00 GMT</pubDate></item>
</channel></rss>"""

GNEWS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Stock Funds Cling to a 10.3% Gain for 2026 - WSJ</title>
<link>https://news.google.com/rss/articles/abc</link><pubDate>Sun, 04 Oct 2026 14:00:00 GMT</pubDate>
<source url="https://www.wsj.com">WSJ</source></item>
<item><title>Here&#8217;s the latest.</title><link>https://x</link><pubDate>Sun, 04 Oct 2026 15:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_feed_cleans_titles_and_drops_filler():
    ft = parse_feed("FT", FT)
    assert [h.title for h in ft] == ["Investors look to shelter portfolios from rising AI concentration risks"]
    wsj = parse_feed("WSJ", GNEWS)
    assert [h.title for h in wsj] == ["Stock Funds Cling to a 10.3% Gain for 2026"]
    assert wsj[0].published == datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)
    assert wsj[0].sources == ["WSJ"]


def item(title, source, hours_ago):
    t = datetime(2026, 10, 5, 12, tzinfo=timezone.utc) - timedelta(hours=hours_ago)
    return Headline(title, f"https://{source}/{hours_ago}", t, [source], title_words(title))


def test_merge_combines_the_same_story_across_sources():
    out = merge([
        item("Fed holds rates steady as inflation cools", "WSJ", 1),
        item("Fed Holds Rates Steady as Inflation Cools", "NYT", 2),
        item("Oil jumps after Gulf tanker attack", "FT", 3),
    ])
    assert [h.title for h in out] == ["Fed holds rates steady as inflation cools", "Oil jumps after Gulf tanker attack"]
    assert out[0].sources == ["WSJ", "NYT"]


def test_merge_keeps_different_stories_apart():
    out = merge([
        item("Fed holds rates steady as inflation cools", "WSJ", 1),
        item("Bank of Japan raises rates for the first time since 2007", "FT", 2),
        item("Oil prices rise on supply fears", "FT", 3),
        item("Gold prices rise on supply fears", "NYT", 4),
    ])
    assert len(out) == 4


def test_merge_dedupes_the_same_url():
    a = item("Jobs report shows hiring slowed in September", "NYT", 1)
    b = item("Hiring slowed in September, jobs report shows", "NYT", 2)
    b.url = a.url  # listed in both the Business and Economy feeds
    assert len(merge([a, b])) == 1


def test_merge_is_newest_first_with_a_per_source_cap():
    topics = ["Treasury", "copper", "Nvidia", "yen", "bitcoin", "Tesla", "housing", "payrolls", "oil", "gold",
              "Apple", "lithium", "airlines", "banks", "Boeing", "wheat", "Samsung", "Intel", "steel", "shipping"]
    items = [item(f"{t} {t}-linked shares swing on {t} news", "WSJ", i) for i, t in enumerate(topics)]
    items += [item(f"{t} outlook darkens for {t} investors", "FT", 30 + i) for i, t in enumerate(["gilts", "euro", "Bund"])]
    out = merge(items, limit=15, per_source=6)
    assert sum(1 for h in out if h.sources[0] == "WSJ") == 6
    assert sum(1 for h in out if h.sources[0] == "FT") == 3
    assert [h.published for h in out] == sorted((h.published for h in out), reverse=True)


def test_feeds_cover_ft_nyt_and_wsj():
    assert {s for s, _ in headlines.FEEDS} == {"FT", "NYT", "WSJ"}


def test_opinion_and_wire_roundups_are_filler():
    assert headlines.is_filler("Opinion | How Not to Fix Britain's Economy")
    assert headlines.is_filler("Basic Materials Roundup: Market Talk")
    assert not headlines.is_filler("U.S. Treasury Selloff Resumes After Brief Respite")
