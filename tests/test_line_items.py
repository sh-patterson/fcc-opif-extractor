"""Tests for line-item extraction from contract PDFs."""

from fcc_ca_ads.line_items import (
    LineItem,
    parse_line_items,
    parse_week_breakdowns,
)


# Realistic line-item text from actual FCC contract filings
LINE_ITEM_TEXT = """\
N 58    KABC     03/03/26  03/08/26   NBA LA Lakers     various     :30    $25,000   NM     1      $25,000
N 59    KABC     03/03/26  03/07/26   5A News           5:00A-5:30A :30    $500      NM     5      $2,500
N 60    KABC     03/03/26  03/07/26   Good Morning Am   7:00A-9:00A :30    $3,000    NM     5      $15,000
N 61    KABC     03/03/26  03/09/26   American Idol     8:00P-10:00P :30   $8,500    NM     1      $8,500
N 62    KABC     03/03/26  03/07/26   Local News 6PM    6:00P-6:30P :15    $2,000    BK     5      $10,000
"""

# Line item with combined length (two :15 spots)
LINE_ITEM_COMBINED_LENGTH = """\
N 70    KABC     03/03/26  03/07/26   Morning Show      6:00A-7:00A :15/:15 $1,200  NM     3      $3,600
"""

# Line item with CDR rate type
LINE_ITEM_CDR = """\
N 71    KABC     03/03/26  03/07/26   Evening News      5:00P-5:30P :30    $4,000   CDR    2      $8,000
"""

# Week breakdown text
WEEK_BREAKDOWN_TEXT = """\
Week: 03/03/26 03/08/26 -1111-- 5 $500
Week: 03/03/26 03/09/26 1111111 7 $3,000
Week: 03/10/26 03/14/26 -1111-- 5 $500
"""

# Full page with mixed content
FULL_PAGE_TEXT = """\
Contract: 424082                          Estimate: 31879
Advertiser: TOM STEYER FOR GOVERNOR 2026

N 58    KABC     03/03/26  03/08/26   NBA LA Lakers     various     :30    $25,000   NM     1      $25,000
N 59    KABC     03/03/26  03/07/26   5A News           5:00A-5:30A :30    $500      NM     5      $2,500
N 60    KABC     03/03/26  03/07/26   Good Morning Am   7:00A-9:00A :30    $3,000    NM     5      $15,000

Totals                      11    $42,500.00
"""


class TestParseLineItems:
    def test_parses_standard_lines(self):
        items = parse_line_items(LINE_ITEM_TEXT)
        assert len(items) == 5

    def test_first_item_fields(self):
        items = parse_line_items(LINE_ITEM_TEXT)
        lakers = items[0]
        assert isinstance(lakers, LineItem)
        assert lakers.line_number == 58
        assert lakers.channel == "KABC"
        assert lakers.start_date == "03/03/26"
        assert lakers.end_date == "03/08/26"
        assert "NBA LA Lakers" in lakers.show_name
        assert lakers.spot_length == ":30"
        assert lakers.rate_per_spot == 25000.0
        assert lakers.rate_type == "NM"
        assert lakers.spots == 1
        assert lakers.line_total == 25000.0

    def test_news_item(self):
        items = parse_line_items(LINE_ITEM_TEXT)
        news = items[1]
        assert news.line_number == 59
        assert "5A News" in news.show_name
        assert news.rate_per_spot == 500.0
        assert news.spots == 5
        assert news.line_total == 2500.0

    def test_fifteen_second_spot(self):
        items = parse_line_items(LINE_ITEM_TEXT)
        local_news = items[4]
        assert local_news.spot_length == ":15"
        assert local_news.rate_type == "BK"
        assert local_news.rate_per_spot == 2000.0

    def test_combined_length(self):
        items = parse_line_items(LINE_ITEM_COMBINED_LENGTH)
        assert len(items) == 1
        assert items[0].spot_length == ":15/:15"

    def test_cdr_rate_type(self):
        items = parse_line_items(LINE_ITEM_CDR)
        assert len(items) == 1
        assert items[0].rate_type == "CDR"

    def test_empty_text(self):
        assert parse_line_items("") == []
        assert parse_line_items("No line items here") == []

    def test_mixed_page_content(self):
        """Should parse line items even when mixed with non-line-item content."""
        items = parse_line_items(FULL_PAGE_TEXT)
        assert len(items) == 3

    def test_line_item_dataclass(self):
        item = LineItem(
            line_number=1,
            channel="KABC",
            start_date="03/03/26",
            end_date="03/07/26",
            show_name="Test Show",
            time_slot="9:00A-10:00A",
            spot_length=":30",
            rate_per_spot=1000.0,
            rate_type="NM",
            spots=5,
            line_total=5000.0,
        )
        assert item.line_number == 1
        assert item.line_total == 5000.0


class TestParseWeekBreakdowns:
    def test_parses_weeks(self):
        weeks = parse_week_breakdowns(WEEK_BREAKDOWN_TEXT)
        assert len(weeks) == 3

    def test_week_fields(self):
        weeks = parse_week_breakdowns(WEEK_BREAKDOWN_TEXT)
        w = weeks[0]
        assert w["start_date"] == "03/03/26"
        assert w["end_date"] == "03/08/26"
        assert w["day_pattern"] == "-1111--"
        assert w["spots"] == 5
        assert w["rate"] == 500.0

    def test_full_week(self):
        weeks = parse_week_breakdowns(WEEK_BREAKDOWN_TEXT)
        w = weeks[1]
        assert w["day_pattern"] == "1111111"
        assert w["spots"] == 7

    def test_empty_text(self):
        assert parse_week_breakdowns("") == []
