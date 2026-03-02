from fcc_ad_tracker.rss import parse_rss_items


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>KABC-TV Political File</title>
    <item>
      <title>Steyer Order Revision</title>
      <link>https://publicfiles.fcc.gov/documents/abc</link>
      <guid>abc-1</guid>
      <pubDate>Mon, 01 Mar 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>NAB Form PB-18</title>
      <link>https://publicfiles.fcc.gov/documents/def</link>
      <guid>def-1</guid>
      <pubDate>Mon, 01 Mar 2026 13:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_items():
    items = parse_rss_items(RSS_XML)
    assert len(items) == 2
    assert items[0].guid == "abc-1"
    assert "Steyer Order" in items[0].title
    assert items[0].published_at is not None


def test_parse_rss_items_empty():
    assert parse_rss_items("") == []
