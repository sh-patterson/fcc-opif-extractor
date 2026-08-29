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
    entries = [element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}]
    for item in entries:
        title = (_child_text(item, "title") or "").strip()
        link_element = _child(item, "link")
        link = ""
        if link_element is not None:
            link = (link_element.text or link_element.get("href") or "").strip()
        guid = (_child_text(item, "guid") or _child_text(item, "id") or link or title).strip()
        pub_date = (
            _child_text(item, "pubDate")
            or _child_text(item, "updated")
            or _child_text(item, "published")
            or ""
        ).strip() or None
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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _local_name(child.tag) == name), None)


def _child_text(element: ET.Element, name: str) -> str | None:
    child = _child(element, name)
    return child.text if child is not None else None
