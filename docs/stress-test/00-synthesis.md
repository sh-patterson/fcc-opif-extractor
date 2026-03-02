# FCC Ad Tracker Stress Test — Synthesis

**Date:** 2026-03-01
**Method:** Four parallel exploration agents auditing regex patterns, error handling, API coverage, and database schema.

---

## Tier 1: Things That Will Break in Production

**1. Extract command crashes on bad PDFs — no recovery**
One corrupt, empty, or password-protected PDF kills the entire extract loop. Every file after it in the queue never gets processed. There's no try/except around `extract_pdf_text()`. This is the #1 thing to fix before scaling.
*(Source: error-handling audit, issue 2.1-2.3)*

**2. No pagination on file history — truncated data**
`get_file_history()` caps at `max_files` (default 100) and never pages. A busy LA station in October 2026 could easily have 300+ political files. We'd silently miss 200 of them. The API supports `offset` — we just never use it.
*(Source: API coverage audit, finding #1)*

**3. Line item double-counting across revisions**
`summary_by_candidate` and `summary_by_show` sum line items across ALL files for a contract number. When Rev 0 and Rev 1 both have line items, spend is double-counted. This silently inflates reported numbers — the worst kind of bug for a research tool.
*(Source: schema audit, bug #1)*

**4. Partial line item extraction is invisible**
If regex matches 5 of 50 line items on a contract, Gemini never fires (it only triggers when count is exactly 0). The user sees $12,500 instead of $125,000 and has no way to know. No logging of "attempted vs matched" lines.
*(Source: error-handling audit, issue 4.3)*

---

## Tier 2: Silent Data Loss

**5. `_LINE_ITEM_RE` is WideOrbit-specific**
The "N" line prefix, single-char `a/p` (not "AM/PM"), `various` lowercase-only, and the `NM|BK|CDR`-only rate types are all WideOrbit conventions. Fox stations running VCreative or Nexstar stations on different traffic systems will produce line items in formats that silently don't match. Every unmatched line is money we don't report.
*(Source: regex audit, pattern #1)*

**6. Orphan line items can't be queried**
When regex finds line items but not a contract number, those items get `contract_number=NULL`. They exist in the DB but are invisible to candidate/advertiser queries (the JOIN fails). Unattributed spend.
*(Source: error-handling audit, issue 4.4)*

**7. `get_file_history` silently returns empty on weird API responses**
If the API returns an unexpected JSON shape, the function returns `[]` instead of raising. The user sees "No file history for KABC" and moves on, not knowing the API actually failed.
*(Source: error-handling audit, issue 1.3)*

**8. Concurrent extract runs create duplicate rows**
No unique constraints on `extractions` or `line_items`. Two extract processes touching the same files double every row. Spend doubles, field counts double.
*(Source: error-handling audit, issue 3.1)*

---

## Tier 3: Scaling Blind Spots

**9. Cross-state DMA problem**
DMAs don't respect state lines. Sacramento DMA includes NV counties; Philadelphia includes NJ. Searching by state misses out-of-state stations that serve target DMAs. Systematic gap for multi-state deployment.
*(Source: API coverage audit, finding #5)*

**10. `download_pdf()` bypasses rate limiting**
The client has a 1 req/sec rate limiter, but `download_pdf()` uses raw `requests.get()` outside the client entirely. Bulk downloads can hammer the FCC CDN unthrottled.
*(Source: API coverage audit, finding #4)*

**11. The NOT IN extraction subquery is a scale bomb**
At 100K files with 500K extraction rows, `NOT IN (SELECT DISTINCT file_id FROM extractions)` becomes very slow. An `extraction_status` column on files would fix it.
*(Source: schema audit, finding #4)*

**12. No re-extract mechanism**
Once a file has any extraction rows, it's permanently skipped. After fixing bugs in regex or adding Gemini, you can't re-process old files without manual DB surgery.
*(Source: error-handling audit, issue 4.6)*

---

## Tier 4: Missing Capabilities That Limit Value

**13. The `/search/api` endpoint is unused**
The FCC has a cross-entity search API with `political_file_type`, `office_type`, and `campaign_year` filters. Could replace station-by-station discovery entirely.
*(Source: API coverage audit, finding #2)*

**14. NAB forms are classified but not extracted**
NAB PB-18 forms contain candidate name, office sought, party affiliation, and federal/state/local designation — structured metadata we're ignoring. Arguably more reliable than regex-parsing contracts.
*(Source: API coverage audit, finding #6)*

**15. No office_sought field anywhere**
`extract_candidate()` parses "STEYER FOR GOVERNOR" and captures "Tom Steyer" but throws away "GOVERNOR." Can't distinguish governor ads from Senate ads from House ads.
*(Source: schema audit, finding #3)*

**16. No candidate normalization**
"TOM STEYER FOR GOVERNOR 2026" vs "Tom Steyer" vs "Thomas Steyer" vs OCR-garbled "Tom Stever" — all treated as different entities. Cross-station analysis fragments.
*(Source: schema audit, finding #6)*

**17. `parse_week_breakdowns()` is dead code**
Parses weekly spot detail (day patterns, per-week rates) but nothing calls it or stores the results. Data needed for time-series analysis.
*(Source: schema audit, finding #7)*

**18. RSS feeds exist but we don't use them**
Each station has an RSS feed at a predictable URL. Better than blind polling every station's file history.
*(Source: API coverage audit, finding #3)*

**19. API timestamps thrown away**
`create_ts` and `last_update_ts` from the file history response aren't stored. Would enable smarter incremental polling instead of the static `--since` date.
*(Source: API coverage audit, finding #7)*

---

## Recommended Fix Order

**Immediate (before next data pull):**
1. try/except around `extract_pdf_text` — 5-minute fix, prevents total extraction failure
2. File history pagination — without this, busy stations have truncated data
3. Fix revision double-counting in summary queries — reported numbers are wrong today

**Before expanding to non-CA stations:**
4. Add a "near-miss" log for line items — know what regex is missing
5. Expand `_LINE_ITEM_RE` for AM/PM, Various, broader rate types
6. Fix cross-state DMA discovery
7. Route `download_pdf()` through rate-limited client

**For production quality:**
8. Add `extraction_status` column to files (replace NOT IN subquery)
9. Add unique constraints to extractions and line_items
10. Add `extraction_method` column for Gemini provenance
11. Add re-extract capability (--force flag or similar)

**For analytical depth:**
12. Capture `office_sought` from advertiser/candidate extraction
13. Build candidate normalization table
14. Wire up `parse_week_breakdowns()` for time-series data
15. Explore FCC `/search/api` for cross-entity discovery
