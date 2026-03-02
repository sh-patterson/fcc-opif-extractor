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

**What is being spent in a congressional district?**
```bash
fcc-ad-tracker load-districts --input data/downballot-cd-to-dma-2024.csv
fcc-ad-tracker summary --by district --state CA
# CA-28 | estimated_spend=$2,978,500 | contracts=14
# CA-30 | estimated_spend=$2,978,500 | contracts=14
```

District-level numbers are estimates. TV markets (DMAs) don't align to congressional districts — the LA DMA covers roughly 18 House districts. Spend is allocated proportionally by population weight across overlapping districts.

**How is spending trending week over week?**
```bash
fcc-ad-tracker summary --candidate "Steyer" --by week
# 2026-01-05 | spots=42 | spend=$55,300
# 2026-03-02 | spots=98 | spend=$152,250
```

## How it works

1. **Discover** TV stations by state and DMA via the FCC facility search API
2. **Download** political file PDFs, deduplicating by SHA-256 hash
3. **Classify** each file as a contract, invoice, NAB form, or traffic order
4. **Extract** structured data:
   - Basic fields (advertiser, candidate, total, flight dates) — works broadly across filing formats
   - Contract metadata (contract number, revision, agency, gross/commission/net totals) — works on structured contracts
   - Per-spot line items (show, time slot, rate, spot count) — regex handles WideOrbit/Strata formats; Gemini Flash handles everything else
   - NAB PB-18/PB-19 forms — political broadcasting disclosure data
5. **Normalize** candidates — auto-resolves candidate names during extraction, with fuzzy matching and manual alias linking
6. **Query** and **summarize** the results — by candidate, station, show, week, or congressional district
7. **Monitor** via RSS — poll station feeds for new filings and auto-download

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
| Line items (per-spot show/rate/daypart) — regex | Strata/WideOrbit format (`N <line#>` rows) | Other buying platform formats |
| Line items — Gemini fallback | Most PDF contract formats (Fox, Tegna, etc.) | Badly scanned or handwritten PDFs |
| NAB forms (PB-18/PB-19) | Standard FCC disclosure forms | Non-standard layouts |

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
fcc-ad-tracker summary --candidate "Steyer" --by week # spend over time
fcc-ad-tracker summary --station KABC-TV --by show    # all campaigns on a station
fcc-ad-tracker summary --by district --state CA       # spend by congressional district

# Candidates
fcc-ad-tracker list-candidates                        # all resolved candidates
fcc-ad-tracker normalize-candidate --canonical "Tom Steyer" --alias "STEYER 2026"
fcc-ad-tracker suggest-candidate-links --apply        # fuzzy-match unlinked contracts

# RSS monitoring
fcc-ad-tracker rss-poll --station KABC-TV             # check for new filings
fcc-ad-tracker rss-sync --station KABC-TV             # poll + download new files
fcc-ad-tracker rss-list --station KABC-TV             # list tracked RSS items

# Districts
fcc-ad-tracker load-districts --input data/downballot-cd-to-dma-2024.csv

# FCC search
fcc-ad-tracker search-api --query "Steyer" --campaign-year 2026

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

SQLite with these tables:

- **stations** — call sign, market/DMA, city, state
- **files** — downloaded PDFs, SHA-256 hash, file type, extraction status (`done`/`error`/`not_applicable`/`no_line_items`)
- **extractions** — per-field results with confidence scores (high/medium/low)
- **contracts** — contract number, revision, agency, gross/commission/net totals, `latest_file_id` for revision tracking
- **line_items** — per-spot: show name, time slot, spot length, rate, rate type, spot count, extraction method (regex/gemini)
- **line_item_weeks** — weekly spend breakdowns per line item
- **candidates** — canonical candidate names with office sought
- **candidate_aliases** — alternate names and committee names linked to candidates
- **nab_forms** — NAB PB-18/PB-19 political broadcasting disclosure data
- **rss_items** — tracked RSS feed items per station
- **districts** — DMA-to-congressional-district crosswalk with population weights

Contract revisions are handled automatically — only the latest revision's line items are used in queries and summaries. Older revisions are pruned during extraction.
