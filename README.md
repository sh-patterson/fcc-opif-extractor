# fcc-ca-ads

[![CI](https://github.com/sh-patterson/fcc-opif-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/sh-patterson/fcc-opif-extractor/actions/workflows/ci.yml)

A CLI tool that extracts political ad filing data from FCC public inspection files (OPIF) for California TV stations. Broadcasters are required to publicly disclose political ad buys -- this tool automates downloading those filings and extracting structured data from them.

## What it does

1. Discovers full-power TV stations in California's major DMAs via the FCC facility search API
2. Downloads political file PDFs from each station's public file history
3. Extracts text from PDFs using pdfplumber (with optional OCR fallback via ocrmypdf)
4. Regex-extracts fields: advertiser, candidate, spend totals, and flight dates
5. Stores everything in a local SQLite database for querying

## Requirements

- Python 3.11+
- For OCR fallback: [Tesseract](https://github.com/tesseract-ocr/tesseract) and the `ocr` extra

## Installation

```bash
pip install -e .

# With OCR support:
pip install -e ".[ocr]"
```

## Quick start

```bash
# 1. Load station data into the database
fcc-ca-ads load-stations

# 2. Download political file PDFs for a station
fcc-ca-ads download --station KABC

# 3. Extract fields from downloaded PDFs
fcc-ca-ads extract

# 4. Query the extracted data
fcc-ca-ads query --candidate "Smith"
```

## CLI commands

### `discover`

Discover TV stations from the FCC facility search API and save to a JSON file.

```
fcc-ca-ads discover [--state CA] [--output data/stations.json]
```

### `load-stations`

Load stations from a JSON seed file into the database.

```
fcc-ca-ads load-stations [--input data/stations.json]
```

### `download`

Download political file PDFs via the FCC file history API.

```
fcc-ca-ads download --station KABC
fcc-ca-ads download --all
fcc-ca-ads download --all --since 2025-06-01 --until 2025-12-31 --limit 50
fcc-ca-ads download --station KNBC --dry-run
```

Options:
- `--station` -- single station call sign
- `--all` -- download for all stations in the database
- `--since` -- start date (default: 2025-01-01)
- `--until` -- end date (default: today)
- `--limit` -- max files per station (default: 100)
- `--dry-run` -- list files without downloading

### `extract`

Extract fields (advertiser, candidate, total spend, flight dates) from all downloaded PDFs that haven't been processed yet.

```
fcc-ca-ads extract
```

### `query`

Query extracted ad data with optional filters.

```
fcc-ca-ads query --candidate "Garcia"
fcc-ca-ads query --advertiser "Committee"
fcc-ca-ads query --market "LOS ANGELES"
fcc-ca-ads query --since 2025-06-01
```

### `status`

Show database summary: station count, files downloaded, files extracted.

```
fcc-ca-ads status
```

### Global options

- `--db PATH` -- SQLite database path (default: `data/ads.db`)
- `-v` / `--verbose` -- enable debug logging

## Data sources

All data comes from the FCC's Online Public Inspection Files (OPIF) system at `publicfiles.fcc.gov`. This is the same public data available through each station's online public file. No authentication is required.

The tool targets California's four largest DMAs: Los Angeles, San Francisco-Oakland-San Jose, Sacramento-Stockton-Modesto, and San Diego.

## Limitations

- **Extraction accuracy varies.** The regex-based field extraction works well on structured FCC contract forms but can miss or misparse less standardized filings. Confidence levels (high/medium/low) are assigned to each extraction.
- **Totals are often per-spot, not contract-level.** Many filings report individual spot rates rather than a single contract total. Aggregating spend requires care.
- **OCR fallback requires Tesseract.** Scanned PDFs without a text layer need `ocrmypdf` and Tesseract installed. Without them, scanned filings are skipped.
- **California only.** The station discovery targets CA DMAs. Other states would require modifying the target DMA list in `config.py`.
