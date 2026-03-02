# fcc-ad-tracker

[![CI](https://github.com/sh-patterson/fcc-opif-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/sh-patterson/fcc-opif-extractor/actions/workflows/ci.yml)

Extracts political ad spending data from FCC public inspection files. TV stations are required to disclose every political ad buy — who's buying, what they're paying, which shows, how many spots. This tool pulls those filings and turns them into structured, queryable data.

## What questions can this answer?

### Today

**What is a candidate spending?**
```bash
fcc-ad-tracker contracts --candidate "Steyer"
# KABC-TV | 424082 | TOM STEYER FOR GOVERNOR 2026 | gross=$522,700 net=$444,295 spots=227

fcc-ad-tracker summary --candidate "Steyer" --by show
# NBA LA Lakers | spots=1 | spend=$25,000 | rate=$25,000-$25,000
# Good Morning America | spots=28 | spend=$84,000 | rate=$3,000-$3,000
# 5A News | spots=14 | spend=$7,000 | rate=$500-$500
```

**What is being spent in a media market?**
```bash
fcc-ad-tracker contracts --market "LOS ANGELES"
fcc-ad-tracker summary --station KABC-TV --by show
```

**Who is buying a specific show?**
```bash
fcc-ad-tracker summary --show "American Idol"
```

### Not yet — needs a DMA-to-district crosswalk

**What is being spent in a congressional district?**

This is the hard problem. TV markets (DMAs) don't align to congressional districts. The LA DMA covers roughly 18 House districts. The Sacramento DMA bleeds into multiple districts that also touch other DMAs. A single ad buy on KABC reaches all of them.

To answer district-level questions you need:
1. A **DMA-to-district mapping** with population weights — what percentage of each district's population falls within each DMA
2. **Spend allocation** — if a candidate spends $500K on LA TV, how much of that is "for" CA-27 vs. CA-34 vs. CA-40
3. A view of whether the ad is actually targeting that district or just happens to reach it (a gubernatorial ad on LA TV isn't really "spending in CA-27")

Nielsen publishes DMA-to-county mappings. Census data maps counties to congressional districts. Combining these would let us estimate district-level exposure, but it's an estimate — not a precise answer. The tool would need a `districts` table and a weighted crosswalk to make this work.

## How it works

1. **Discover** TV stations by state and DMA via the FCC facility search API
2. **Download** political file PDFs, deduplicating by SHA-256 hash
3. **Classify** each file as a contract, invoice, NAB form, or traffic order
4. **Extract** structured data:
   - Basic fields (advertiser, candidate, total, flight dates) — works broadly across filing formats
   - Contract metadata (contract number, revision, agency, gross/commission/net totals) — works on structured contracts
   - Per-spot line items (show, time slot, rate, spot count) — works on Strata/WideOrbit format contracts
5. **Query** and **summarize** the results

## What the data actually is

These filings are required by [47 CFR 73.1943](https://www.law.cornell.edu/cfr/text/47/73.1943). They contain:
- The actual negotiated rate for each spot (not list prices)
- Which shows and dayparts the ads run in
- Agency commissions (typically 15%)
- Contract revisions — spots added, dropped, or rescheduled

This is the same data available through each station's online public file at `publicfiles.fcc.gov`. No authentication required.

## Scope

**Works for any US state.** The FCC API is national. The tool defaults to California's four largest DMAs (Los Angeles, San Francisco, Sacramento, San Diego) but targeting other states is a config change — update `DEFAULT_TARGET_DMAS` in `config.py`.

**Three tiers of extraction accuracy:**

| What | Works on | Doesn't work on |
|------|----------|-----------------|
| Basic fields (advertiser, candidate, total, dates) | Most political filings | Badly scanned PDFs without OCR |
| Contract metadata (contract #, agency, gross/net) | Structured contracts with labeled fields | Handwritten or non-standard formats |
| Line items (per-spot show/rate/daypart) | Strata/WideOrbit format (`N <line#>` rows) | Other buying platform formats |

**Not covered:** Radio stations, low-power/translator TV stations, reconciliation docs (what actually aired vs. ordered), invoice-specific fields.

## Requirements

- Python 3.11+
- For OCR fallback: [Tesseract](https://github.com/tesseract-ocr/tesseract) and the `ocr` extra
- For Gemini fallback: a Google API key (`GOOGLE_API_KEY`) and the `gemini` extra

## Installation

```bash
pip install -e .

# With OCR support:
pip install -e ".[ocr]"

# With Gemini fallback support:
pip install -e ".[gemini]"

# With OCR + Gemini:
pip install -e ".[ocr,gemini]"
```

## Usage

```bash
# Setup
fcc-ad-tracker load-stations                          # load station data
fcc-ad-tracker discover --state CA                    # or discover from FCC API

# Download
fcc-ad-tracker download --station KABC-TV             # one station
fcc-ad-tracker download --all                         # all stations in DB
fcc-ad-tracker download --all --since 2026-01-01      # date range
fcc-ad-tracker download --station KNBC-TV --dry-run   # preview without downloading

# Extract
fcc-ad-tracker extract                                # process all unextracted PDFs
fcc-ad-tracker extract --use-gemini                  # force Gemini fallback on
fcc-ad-tracker extract --no-gemini                   # force Gemini fallback off

# Query
fcc-ad-tracker query --candidate "Garcia"             # search extractions
fcc-ad-tracker contracts --candidate "Steyer"         # contract-level totals
fcc-ad-tracker summary --candidate "Steyer"           # spend by station
fcc-ad-tracker summary --candidate "Steyer" --by show # spend by show
fcc-ad-tracker summary --station KABC-TV --by show    # all campaigns on a station

# Export
fcc-ad-tracker contracts --format csv > contracts.csv
fcc-ad-tracker contracts --format json
fcc-ad-tracker query --format csv
```

All commands support `--db PATH` to specify the database location (default: `data/ads.db`) and `-v` for debug logging.

### Gemini fallback

Gemini is optional and only used as a fallback when:
- contract number is missing from regex extraction, or
- no line items were matched by regex

Setup:

```bash
pip install -e ".[gemini]"
cp .env.example .env
# then set GOOGLE_API_KEY in .env
```

By default, `extract` auto-enables Gemini when `GOOGLE_API_KEY` is set.
Use `--use-gemini` or `--no-gemini` to override.
The CLI automatically loads `.env` at startup.

## Database

Five tables in SQLite:

- **stations** — call sign, market/DMA, city, state
- **files** — downloaded PDFs, SHA-256 hash, file type (contract/invoice/nab/traffic), OCR status
- **extractions** — per-field results with confidence scores (high/medium/low)
- **contracts** — contract number, revision, agency, gross/commission/net totals, demographic target
- **line_items** — per-spot: show name, time slot, spot length, rate, rate type, spot count

## What would it take to add district-level analysis

The gap between "what's being spent in a DMA" and "what's being spent in a congressional district" is a crosswalk table. Here's what that looks like:

1. **DMA-to-county mapping** — Nielsen publishes these annually. Each county belongs to exactly one DMA.
2. **County-to-district mapping** — Census/redistricting data. Counties split across multiple districts need population weighting.
3. **A `dma_districts` crosswalk table** — joining the two above, with a `weight` column representing the share of each district's population within each DMA.
4. **A `--district` flag** on `summary` and `contracts` — that joins through the crosswalk and allocates spend proportionally.

The hard part isn't the code — it's that the allocation is inherently imprecise. A $25,000 Lakers spot on KABC reaches all 18 districts in the LA DMA. Allocating $1,389 to each district by population share is mathematically defensible but editorially debatable. The right framing is probably "estimated ad exposure" rather than "ad spend in district X."
