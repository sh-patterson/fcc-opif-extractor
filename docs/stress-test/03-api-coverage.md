# FCC OPIF API Coverage & Client Limitations

**Date:** 2026-03-01
**Scope:** client.py, config.py, discover.py, download.py

---

## 1. API Endpoint Coverage

**Endpoints we use (5):**
- `GET /api/service/facility/search/{state}?format=json` — Facility keyword search, filtered to the exact state by the client
- `GET /api/manager/folder/parentFolders.json` — Get top-level folders for an entity
- `GET /api/manager/folder/id/{folderId}.json` — Get folder contents
- `GET /api/manager/file/history.json` — File history with date range
- `GET https://files.fcc.gov/download/{fileManagerId}.pdf` — Download directly from the FCC CDN

**Endpoints that exist but we DON'T use:**
- `GET https://www.fcc.gov/search/api` — Full-text search across ALL entities' political files. Supports filters for `political_file_type`, `source_service_code`, `office_type`, `campaign_year`. This is a major gap — it could let us find political files across all stations without needing to discover stations first, and filter by campaign year or office type.
- RSS feeds at `https://publicfiles.fcc.gov/tv-profile/{callsign}/rss/` — Per-station RSS for new document notifications.
- Entity profile endpoints (e.g., `/tv-profile/{callsign}/political-files`) — Web-facing but may expose additional metadata.
- Endpoints for AM, FM, cable, DBS, and SDARS services beyond just TV.

**Key gap:** The `/search/api` endpoint with political file filters could be transformative — it provides a cross-entity search with campaign_year and office_type filtering that our current station-by-station approach can't do.

---

## 2. State Scalability

**Current state:** Config targets 4 CA DMAs only. The `discover` command calls `search_facilities(state)` one state at a time.

**50-state scale:**
- ~1,777 full-power TV stations exist nationwide
- CA alone has dozens of full-power stations; we filter to 4 DMAs
- For 50-state: need to call `search_facilities()` for each state (50 API calls, easily cacheable)
- The DMA filter in `discover_stations()` is hardcoded to `DEFAULT_TARGET_DMAS` (CA-only)
- **Station count estimate for competitive races:** Targeting ~60-80 competitive races → 40-60 DMAs → ~300-500 stations
- **For ALL stations:** ~1,777 full-power TV

**What would need to change:**
- `DEFAULT_TARGET_DMAS` needs to be configurable per-state or replaced with target-districts approach
- The `discover` CLI command hardcodes `target_dmas=DEFAULT_TARGET_DMAS` — needs a `--dma` flag or auto-derive from district crosswalk
- The district crosswalk already maps districts to DMAs, so the infrastructure for multi-state is partially there

---

## 3. Date Range Handling

**Current implementation:** `get_file_history()` takes `start_date`, `end_date`, `count` (default 100), and `offset` (default 0). CLI defaults `--since` to `2025-01-01`.

**API limits:**
- FCC OPIF system online since 2012 (TV), expanded to radio/cable 2014-2016
- FCC retention requirement is 2 years for political files — stations may purge older content
- Going back to 2020 is probably viable for many stations; 2015 would have significant gaps

**Critical limitation: No pagination loop.**
The code makes a single call with `count=max_files` (default 100). If a busy station has 300 files, we miss 200. The API supports `offset` but we never use it beyond the initial call.

---

## 4. File History vs Folder Tree

**Both approaches exist in the code:**
- **File history** (`get_file_history`): Used by CLI. Returns flat list with timestamps. Comment says "more reliable than folder tree walk."
- **Folder tree** (`walk_folder_tree` in `download.py`): Recursively walks folders. Currently dead code — not used by CLI.

**File history advantages:**
- Date-filtered — only get files in target window
- Flat structure — no recursion needed
- Includes `file_folder_path` showing tree position

**File history disadvantages:**
- Files uploaded before `--since` date are missed (e.g., multi-year contract uploaded in 2024 for 2026 cycle)

**Folder tree advantages:**
- Gets ALL files regardless of date
- Preserves folder hierarchy
- Can find files predating the `--since` window

**Recommendation:** File history for incremental polling; folder tree for initial full sweep.

---

## 5. File Type Coverage

**What exists in FCC political files:**
- **Contracts/Orders** — Primary target. Ad buy agreements.
- **NAB Forms** — PB-18 (candidate ads) and PB-19 (issue ads). Standardized disclosure forms.
- **Invoices** — Post-airing billing showing what actually ran vs. ordered.
- **Traffic instructions** — Scheduling details, when spots actually aired.
- **Make-goods/Rebates** — Credits and re-runs.
- **Disclosure forms** — Advertiser identity disclosures.
- **Correspondence** — Letters, emails.

**What we classify and extract from:**
- `contract` — Primary extraction target ✓
- `nab` — Detected but NOT extracted (high-value metadata ignored)
- `invoice` — Detected but NOT extracted (ground truth for actual airings ignored)
- `traffic` — Detected but NOT extracted
- `unknown` — Catch-all

**Gap:** NAB forms contain candidate name, office sought, party affiliation, and federal/state/local designation — structured metadata we're ignoring. Invoices contain what actually aired (vs. ordered).

---

## 6. Caching Strategy

**Cached (24h TTL):**
- `search_facilities()` — Station lists. Correct to cache.
- `get_parent_folders()` — Folder structure. Correct to cache.

**Not cached:**
- `get_file_history()` — Freshness mechanism. Correct NOT to cache.
- `get_download_url()` — Builds the stable FCC CDN URL locally. No cache or resolver call needed.
- `get_folder()` — Not cached. Should consider caching for folder tree walks.

**Missing:** No cache invalidation beyond TTL expiry. No way to force-refresh-and-store (only `--no-cache` which disables entirely).

---

## 7. Rate Limiting

**Implementation:**
- Global rate limiter — single `_rate_lock` shared across all endpoints
- Default delay: 1.0 second between requests
- Thread-safe via `threading.Lock`

**At scale:**
- 500 stations × 1 history call = ~8.3 minutes just for history
- 25,000 downloads = ~14 hours at 1 req/sec
- `--workers` flag enables concurrent downloads but rate limiter is global — concurrency buys nothing for API calls

**Critical issue: `download_pdf()` bypasses rate limiting.**
Uses raw `requests.get()` outside the client. Bulk downloads can hammer the FCC CDN unthrottled.

---

## 8. Station Discovery Gaps

**Current filter chain:**
1. `search_facilities(state)` — All TV facilities in a state
2. `full_power_only` filter — Excludes "Low Power"
3. `target_dmas` filter — Only keeps stations in target DMAs

**What this misses:**
- **Class A TV stations** — Required to maintain political files. `is_full_power` check doesn't match "Class A".
- **Radio stations (AM/FM)** — OPIF API covers radio. Political ad spending is significant in smaller markets.
- **Cable systems** — Required to maintain political files. Different API path.
- **Cross-state DMA stations** — A Reno, NV station serving Sacramento DMA. State filter "CA" misses it. This is the biggest gap — DMAs don't respect state boundaries.
- **Inactive stations** — `activeInd: "Y"` exists in API but we don't filter on it.

---

## 9. Data Freshness

**Current approach:** Polling via `download --since`.

**Available mechanisms we don't use:**
- **RSS feeds** — Per-station at predictable URLs. Better than blind polling.
- **`last_update_ts`** — History response includes it. Could track per-station for smarter incremental polling.
- **`history_status`** — "new", "replaced", "deleted". We don't track replacements or deletions.

**Recommendation:** Store latest `last_update_ts` per station after each download run. Use as starting point for next poll.

---

## 10. Missing Metadata

**API fields we throw away:**
- `history_status` — "new" vs. replaced/deleted
- `create_ts` — File creation timestamp (we only store `downloaded_at`)
- `last_update_ts` — Last modification on FCC side
- `file_status` — "com_prc", "pending", "upl", "cvt", "ins", "cpy", "err", "err_cvt"
- `file_extension` — We assume .pdf
- `networkAffiliate` — ABC, CBS, NBC, FOX (useful for analysis)
- `activeInd` — Whether station is currently active

**From `/search/api` (unused):**
- `nielsen_dma_rank` — DMA's Nielsen ranking
- `political_file_type`, `office_type`, `campaign_year` — Available as filters

---

## Summary — Top Findings (Priority Order)

1. **No pagination in file_history** — Busy stations have truncated data
2. **`/search/api` endpoint is unused** — Cross-entity search with campaign_year and office_type filters
3. **RSS feeds exist but aren't used** — Better than blind polling
4. **`download_pdf()` bypasses rate limiting** — Unthrottled CDN requests
5. **Cross-state DMA blind spot** — State-based search misses out-of-state stations in target DMAs
6. **NAB forms and invoices classified but not extracted** — High-value metadata discarded
7. **API timestamps thrown away** — `create_ts` and `last_update_ts` not stored
8. **Class A stations excluded** — `is_full_power` filter too narrow
9. **Folder tree walk is dead code** — Useful for initial full sweep but not wired into CLI
10. **No network affiliate data stored** — Available from facility search
