# Database Schema & Query Gap Audit

**Date:** 2026-03-01
**Scope:** schema.sql, queries.py, connection.py, data model dataclasses

---

## 1. Schema Completeness — What We're NOT Capturing

**Missing from contracts:**
- **Buyer/contact info**: FCC filings often list buyer name, phone, email.
- **Payment terms**: Net 15/30/60 days, make-good provisions.
- **Office sought**: We capture `candidate` but not the race type (Governor, US Senate, US House, Assembly). `extract_candidate()` parses "STEYER FOR GOVERNOR" and captures "Tom Steyer" but throws away "GOVERNOR". Can't distinguish governor ads from Senate ads.
- **Political party**: Not captured anywhere.
- **Ballot measure vs candidate**: No `ad_type` field to distinguish candidate buys from ballot measure buys.

**Missing from line_items:**
- **`contract_id` column**: Only has `contract_number` (TEXT), not the compound `contract_id` (`entity_id:contract_number`). The join compensates with `AND f.entity_id = c.entity_id`, but the relationship is implicit rather than enforced.
- **`extraction_method` column**: No way to tell if a line item came from regex or Gemini. Scratchpad logs it but DB doesn't persist it.
- **Week breakdown data**: `parse_week_breakdowns()` parses weekly spot detail but nothing calls it or stores it. Dead code with useful data going to waste.
- **Day-of-week pattern**: The `_WEEK_RE` captures a 7-char day pattern but there's no column for it.

**Missing from files:**
- **`extraction_method`**: Was this file extracted by regex, Gemini, or both?
- **`extraction_status`**: Currently inferred via `file_id NOT IN (SELECT DISTINCT file_id FROM extractions)`. This subquery gets slow at scale and can't distinguish "extracted with 0 results" from "never attempted."
- **`page_count`**: Not stored. Would help validate extraction completeness.

---

## 2. Data Integrity

**Foreign keys that exist (good):**
- `files.entity_id` → `stations.entity_id` ✓
- `extractions.file_id` → `files.file_id` ✓
- `contracts.entity_id` → `stations.entity_id` ✓
- `contracts.latest_file_id` → `files.file_id` ✓
- `line_items.file_id` → `files.file_id` ✓
- FK enforcement is ON (`PRAGMA foreign_keys = ON`) ✓

**Foreign keys MISSING:**
- `line_items.contract_number` has NO FK to `contracts.contract_number`. Just a TEXT field. Orphaned line items possible if contract is deleted or number doesn't match.
- `line_items` has no reference to `contracts.contract_id` at all. Join is done at query time via `contract_number + entity_id`.

**Orphaned record scenarios:**
- Line items without contracts: Possible when regex finds line items but fails to find a contract number (`contract_num = None`). These become unqueryable by candidate/advertiser.
- Contracts with `latest_file_id` pointing to a file physically deleted from disk: FK only ensures file row exists, not actual file.

**Duplicate contract numbers across stations:**
- `contract_id = f"{entity_id}:{contract_number}"` handles this correctly. Two stations with contract "424082" are separate records. Sound design.

---

## 3. NULL Semantics — Ambiguous States

**"Not found" vs "not applicable" — indistinguishable:**
- `contracts.candidate = NULL` — regex didn't find a candidate? Or this is a ballot measure ad? No way to tell.
- `contracts.gross_total = NULL` — totals block not found? Or contract genuinely has no dollar amount?
- `line_items.rate_per_spot = NULL` — regex explicitly allows this (optional capture group), but could also mean OCR garbled the number.

**Regex vs Gemini provenance — not tracked:**
- After Gemini fallback, we CANNOT tell which fields came from which method.
- The scratchpad logs the method but that's a JSON log file, not queryable.
- The `extractions` table has `confidence` (high/medium/low) but that's regex confidence, not a method marker.

**Recommendation:** Add `extraction_method` column (`regex`, `gemini`, `regex+gemini`) to `contracts` and `line_items`.

---

## 4. Scale Concerns

**Existing indexes (good coverage):**
- `idx_files_entity` on `files(entity_id)` ✓
- `idx_extractions_file` on `extractions(file_id)` ✓
- `idx_extractions_field` on `extractions(field_name)` ✓
- `idx_contracts_entity` on `contracts(entity_id)` ✓
- `idx_contracts_number` on `contracts(contract_number)` ✓
- `idx_line_items_file` on `line_items(file_id)` ✓
- `idx_line_items_contract` on `line_items(contract_number)` ✓
- `idx_dma_districts_district` on `dma_districts(district)` ✓
- `idx_dma_districts_market` on `dma_districts(fcc_market)` ✓

**Missing indexes (hurt at 100K+ files):**
- **`files.sha256`** — `file_exists_by_sha256()` does full table scan. Runs on every download.
- **`files.downloaded_at`** — Used in `query_extractions` with `since` filter.
- **Composite `(entity_id, contract_number)`** — The line_items join pattern uses both.

**LIKE queries can't use indexes:**
- `contracts.candidate` and `contracts.advertiser` queries use `%Steyer%` leading wildcards. Full scans at scale.

**The extraction subquery is the biggest scale bomb:**
```sql
WHERE f.file_id NOT IN (SELECT DISTINCT file_id FROM extractions)
```
At 100K files with 500K+ extraction rows, this is slow. An `extraction_status` column would replace it with an indexed lookup.

**SQLite suitability:**
- WAL mode helps concurrent reads.
- Every query function calls `conn.commit()` individually — many fsyncs. Batching would help enormously.
- For single analyst on CLI: fine. For web service or multi-user: write contention.

---

## 5. Revision Handling

**Current logic works correctly for ordering:**
- Rev 2 before Rev 1 → Rev 2 wins, Rev 1 skipped (`1 >= 2` is False). Correct.
- Rev 1 before Rev 0 → Rev 1 wins, Rev 0 skipped. Correct.

**Problems:**
- **Equal revision numbers**: Two files with `revision_number = 0` → `0 >= 0` is True → second overwrites first. Could replace data with worse extraction. No history kept.
- **No revision history**: When revision overwrites a contract, old data is gone. Only `latest_file_id` is kept.

**BUG: Line item double-counting across revisions.**
Line items are INSERT-only, keyed on `file_id`. Each revision is a different file. But `contract_number` is shared. Queries aggregating by `contract_number` (like `summary_by_candidate` and `summary_by_show`) sum line items across ALL revisions. If Rev 0 has 60 items and Rev 1 has 50, the DB shows 110 items and doubled spend.

---

## 6. Candidate/Advertiser Normalization

**Current state: No normalization at all.**
- `contracts.candidate` and `contracts.advertiser` are free-text fields from regex extraction.
- "TOM STEYER FOR GOVERNOR 2026" and "Tom Steyer" stored as-is.
- No `candidates` table, no `advertisers` table, no canonical name mapping.
- LIKE queries paper over inconsistency but fail for:
  - Misspelled OCR output: "Tom Stever"
  - Different name forms: "Steyer, Tom" vs "Tom Steyer" vs "Thomas Steyer"
  - Committee variations: "TOM STEYER FOR GOVERNOR 2026" vs "FRIENDS OF TOM STEYER"

**Recommendation:** A `candidates` table with `canonical_name`, `aliases`, and `office_sought`. Map via fuzzy matching or manual CLI command.

---

## 7. District Crosswalk

**Weight system:**
- Crosswalk is `downballot-cd-to-dma-2024.csv` — current for 2026 races.
- Weight = `population_in_DMA / total_district_population`. Reasonable proxy.
- `insert_crosswalk` does DELETE-then-INSERT. Swapping crosswalk file is clean.

**At-large districts:** Handled correctly. Tests verify explicitly.

**Territories and special elections:**
- No DC, PR, GU, USVI, or AS in crosswalk.
- Special elections not modeled — no election date or race type.

**Market matching fragility:**
- `auto_match_markets` does EXACT uppercase match. FCC abbreviations like "SACRAMNTO-STKTON-MODESTO" won't match "Sacramento-Stockton-Modesto".
- `map-dma` CLI command exists as manual fix. Good escape hatch but requires manual intervention.

---

## 8. Missing Query Capabilities

**Can't answer today:**
1. **Spend per week / time-series** — Line items have dates but no query groups by date range. Week breakdown data parsed but never stored.
2. **All candidates in a race** — No `office_sought` to group by race.
3. **Average rate by station/spot-length** — No query for rate comparison.
4. **File-level completeness** — "Which files had 0 extractions?" Only via slow NOT IN subquery.
5. **Extraction quality metrics** — "What % of files needed Gemini?" Not in DB.
6. **Market-level spend** — Have to go through districts. No direct market → spend query.
7. **Agency analysis** — "Which agency spends the most?" No `summary_by_agency`.
8. **Revision history** — "How did spend change between revisions?" No history table.
9. **Multi-candidate race view** — No race/office field to group by.
10. **Spot-length mix** — "What % of spend is :30 vs :15?" No summary by spot_length.

---

## Summary — Highest Priority Issues

**Bugs:**
1. **Line item double-counting across revisions** — Inflates spend totals.

**Missing columns (high impact):**
2. **`extraction_method`** on contracts and line_items
3. **`office_sought`** on contracts
4. **`extraction_status`** on files (replaces slow NOT IN subquery)

**Missing indexes:**
5. **`files.sha256`** — Dedup check does full table scan

**Normalization gaps:**
6. **No candidate normalization** — Cross-station analysis will fragment

**Dead code:**
7. **`parse_week_breakdowns()`** — Parses useful data but nothing stores it
