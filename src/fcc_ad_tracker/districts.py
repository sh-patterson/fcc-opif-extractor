from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def load_crosswalk_csv(path: str | Path) -> list[dict]:
    """Parse the Downballot CD-to-DMA crosswalk CSV.

    Expected columns: CD, Media market, State, Population, Percentage
    Population may have commas (e.g. "457,127"), Percentage has % suffix (e.g. "62.3%").
    Rows with Media market == "[None]" are skipped (population outside any DMA).
    """
    rows: list[dict] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dma = row["Media market"].strip()
            if dma == "[None]":
                continue

            pop_raw = row["Population"].strip().replace(",", "")
            pct_raw = row["Percentage"].strip().rstrip("%")

            rows.append({
                "state": row["State"].strip(),
                "district": row["CD"].strip(),
                "dma_name": dma,
                "population": int(pop_raw) if pop_raw else 0,
                "weight": float(pct_raw) / 100.0,
            })
    return rows


def auto_match_markets(
    conn: sqlite3.Connection, rows: list[dict]
) -> tuple[dict[str, str], list[str]]:
    """Try to match each unique DMA name to an FCC station market.

    Returns (matched, unmatched) where matched is {dma_name: fcc_market}
    and unmatched is a list of DMA names with no station match.
    """
    # Get all unique markets from stations table
    station_markets = {
        r["market"].upper(): r["market"]
        for r in conn.execute("SELECT DISTINCT market FROM stations WHERE market IS NOT NULL")
        if r["market"].strip()
    }

    unique_dmas = {r["dma_name"] for r in rows}
    matched: dict[str, str] = {}
    unmatched: list[str] = []

    for dma in sorted(unique_dmas):
        upper = dma.upper()
        if upper in station_markets:
            matched[dma] = station_markets[upper]
        else:
            unmatched.append(dma)

    return matched, unmatched


def insert_crosswalk(
    conn: sqlite3.Connection,
    rows: list[dict],
    market_map: dict[str, str],
) -> int:
    """Bulk insert crosswalk rows into dma_districts. Returns count inserted."""
    # Clear existing data (reload is idempotent)
    conn.execute("DELETE FROM dma_districts")
    count = 0
    for r in rows:
        fcc_market = market_map.get(r["dma_name"])
        conn.execute(
            """
            INSERT INTO dma_districts (district, dma_name, fcc_market, state, population, weight)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (r["district"], r["dma_name"], fcc_market, r["state"], r["population"], r["weight"]),
        )
        count += 1
    conn.commit()
    return count


def update_market_mapping(
    conn: sqlite3.Connection, dma_name: str, fcc_market: str
) -> int:
    """Manually map a DMA name to an FCC market string. Returns rows updated."""
    cursor = conn.execute(
        "UPDATE dma_districts SET fcc_market = ? WHERE dma_name = ?",
        (fcc_market, dma_name),
    )
    conn.commit()
    return cursor.rowcount
