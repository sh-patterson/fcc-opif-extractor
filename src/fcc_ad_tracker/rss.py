"""RSS parsing for FCC station profile feeds."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class RssItem:
    guid: str
    title: str
    link: str
    published_at: str | None
    raw_xml: str


def parse_rss_items(xml_text: str) -> list[RssItem]:
    if not xml_text.strip():
        return []

    root = ET.fromstring(xml_text)
    items: list[RssItem] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        pub_date = (item.findtext("pubDate") or "").strip() or None
        raw_xml = ET.tostring(item, encoding="unicode")
        if not guid:
            continue
        items.append(
            RssItem(
                guid=guid,
                title=title,
                link=link,
                published_at=pub_date,
                raw_xml=raw_xml,
            )
        )
    return items
