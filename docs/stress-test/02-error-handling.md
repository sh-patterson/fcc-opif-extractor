# Error Handling & Silent Failure Audit

**Date:** 2026-03-01
**Scope:** All error paths in cli.py, client.py, extract.py, download.py, gemini_extract.py

---

## 1. API Failure Modes

**GOOD: Client has solid retry logic** (`client.py:30-75`)
- Retries on 408, 429, 500, 502, 503, 504 with exponential backoff + jitter
- Rate limiting with thread-safe lock
- Configurable timeout (30s default)

**ISSUE 1.1: 403 Forbidden not handled gracefully**
- In `discover` and `get_file_history`, a 403 propagates as an unhandled exception + ugly traceback.
- In `_download_station`, the generic `except Exception` catches it — file is skipped. Acceptable.
- **Severity:** User confusion (ugly traceback instead of clean error).

**ISSUE 1.2: Malformed JSON from API**
- If API returns HTML error page or truncated response, `resp.json()` raises `JSONDecodeError`.
- In `_download_station`: caught by generic except. OK.
- In `discover_stations`: unhandled, crashes with traceback.
- **Severity:** User confusion.

**ISSUE 1.3: `get_file_history` silently returns empty on unexpected responses**
- If API returns an unexpected JSON shape (not a dict, or missing expected keys), it falls through to returning an empty list.
- User sees "No file history for KABC" and thinks there's nothing to download when the API actually failed.
- **Severity: Silent data loss** — whole stations appear to have no files.

**ISSUE 1.4: `get_download_url` missing Location header**
- If API returns 302 without a `Location` header, `resp.headers["Location"]` raises `KeyError`.
- Caught by generic except in `_download_station`, but error message is confusing.

---

## 2. PDF Edge Cases

**ISSUE 2.1: Empty/0-byte PDFs — CRASHES EXTRACT**
- `download_pdf` saves a 0-byte response (server returns 200 with empty body).
- `extract_pdf_text` → `pdfplumber.open()` on a 0-byte file raises an exception.
- The `extract` command has NO try/except around `extract_pdf_text`. The entire extract loop crashes.
- **Severity: HIGH — crashes extract command, no remaining files get processed.**

**ISSUE 2.2: Corrupted/partial PDFs — CRASHES EXTRACT**
- Same as 2.1. Partial downloads cause pdfplumber to raise. Same crash-the-loop problem.
- **Severity: HIGH.**

**ISSUE 2.3: Password-protected PDFs — CRASHES EXTRACT**
- pdfplumber raises on password-protected PDFs.
- **Severity: HIGH — same crash.**

**ISSUE 2.4: Scanned-only PDFs without ocrmypdf**
- The OCR fallback works correctly — `RuntimeError` is caught, returns `ExtractionResult` with `has_text=False` and `error` set.
- BUT: the caller in `cli.py` never checks `result.error`. Continues processing near-empty text. File gets `mark_ocr_done` called.
- **Severity: MEDIUM — silent data loss.** File marked as processed but nothing was extracted.

**ISSUE 2.5: Very large PDFs (100+ pages)**
- No memory or time limits. pdfplumber loads entire PDF.
- Gemini prompt concatenates ALL non-T&C pages. Could exceed context window. Gemini call fails silently (returns None).
- **Severity: LOW** — functional but slow, Gemini fallback silently fails.

**ISSUE 2.6: OCR output file not cleaned up**
- Creates `_ocr.pdf` next to original. Never deleted. Disk bloat.
- **Severity: LOW.**

---

## 3. Database Edge Cases

**ISSUE 3.1: Concurrent `extract` runs — DUPLICATE DATA**
- Two simultaneous runs get overlapping file lists.
- `extractions` table: No unique constraint. Duplicate rows inserted.
- `line_items` table: Same problem. Duplicate line items.
- `contracts` table: Has `ON CONFLICT(contract_id) DO UPDATE`. Tolerable.
- **Severity: HIGH — silent data duplication.** Doubled counts, spend, etc.

**ISSUE 3.2: Concurrent `download` (--workers > 1)**
- Each thread creates its own connection. WAL mode handles concurrent writes.
- The dedup check and insert are NOT atomic — two threads could both check, both find no match, and both download.
- Every operation does individual `conn.commit()`. Many small transactions under load.
- **Severity: LOW** — functional but slower than necessary.

**ISSUE 3.3: Read-only database blocks read-only commands**
- `init_schema` runs on every connection (connection.py), even for read-only commands like `query` and `status`.
- `conn.executescript()` fails with `OperationalError: attempt to write a readonly database`.
- **Severity: MEDIUM — query commands should work on read-only DB but can't.**

**ISSUE 3.4: File record exists but PDF deleted from disk**
- `extract` command correctly skips missing files (`if not path or not path.exists(): continue`).
- But silently — user doesn't know files are being skipped.

**ISSUE 3.5: Every DB write does a separate commit**
- Every function in `queries.py` calls `conn.commit()` individually. For 500 files, that's thousands of fsync operations.
- **Severity: LOW (performance)** — transaction batching would be 10-100x faster.

---

## 4. Silent Data Loss

**ISSUE 4.1: Files classified as "unknown"**
- Extraction proceeds the same regardless of file_type. Not an issue for extraction.
- But no way to flag unclassifiable files for manual review.
- **Severity: LOW.**

**ISSUE 4.2: T&C page misclassification**
- `is_terms_and_conditions` only checks first 200 chars for specific headers.
- If a contract page happens to start with "STANDARD TERMS" in rate descriptions, it gets skipped. All fields and line items on that page are lost.
- **Severity: MEDIUM — false positives cause silent data loss.**

**ISSUE 4.3: Line items that don't match regex just vanish**
- `parse_line_items` uses `finditer()`. Lines that don't match are silently skipped.
- No count of "lines attempted vs lines matched". No logging.
- Gemini fallback only triggers when `regex_line_count == 0` for the ENTIRE file. If regex matches 3 out of 50 line items, Gemini never fires.
- **Severity: HIGH — partial extraction with no visibility.** A contract with 50 line items might only extract 5, and the user has no idea. Reported spend ~90% too low.

**ISSUE 4.4: Contract numbers that don't match leave orphan data**
- If `extract_contract_number` returns `None`, line items get `contract_number=None`.
- These orphan line items can't be linked to any contract. `query_line_items` JOIN fails, so `candidate` and `advertiser` are NULL.
- Querying `summary --candidate Steyer` won't find these line items.
- **Severity: HIGH — line items exist in DB but are invisible to candidate/advertiser queries.**

**ISSUE 4.5: Gemini fallback doesn't fill partial regex results**
- Gemini only fires when contract number is completely missing OR line items are completely missing.
- If regex found a contract number AND some (but not all) line items, Gemini does NOT fire.
- **Severity: covered by 4.3.**

**ISSUE 4.6: No re-extract mechanism**
- Files filtered by `file_id NOT IN (SELECT DISTINCT file_id FROM extractions)`.
- If extraction was partial (crashed mid-file, or only got fields but not line items), no way to re-extract.
- Deleting from `extractions` table manually is the only workaround.
- **Severity: MEDIUM — after fixing bugs, old files can't benefit without manual DB surgery.**

---

## 5. Concurrency Issues

**ISSUE 5.1: Shared `requests.Session` across threads**
- `OpifClient.session` is a single `requests.Session`. `requests.Session` is NOT thread-safe.
- Rate limiting is thread-safe (uses Lock). But HTTP calls through `self.session.request()` are not protected.
- **Severity: MEDIUM — intermittent connection errors under concurrent load.**

**ISSUE 5.2: `click.echo` from multiple threads**
- `_process_file` calls `click.echo()` from worker threads. Not thread-safe.
- **Severity: LOW — cosmetic only.**

**ISSUE 5.3: Scratchpad logging from threads**
- Uses `threading.Lock()` around file writes. **Thread-safe. No issue.**

---

## 6. Progress/Reporting Gaps

**ISSUE 6.1: Extract command doesn't report per-file errors**
- If `extract_pdf_text` raises, entire command crashes. No per-file error reporting.

**ISSUE 6.2: No count of skipped files**
- Files with missing PDFs silently skipped via `continue`.
- End message only reports successes: "Extracted fields from 47 files" — doesn't mention 12 were skipped.

**ISSUE 6.3: No extraction quality reporting**
- Doesn't report: how many files had 0 fields, 0 line items, needed Gemini, Gemini failed.
- Scratchpad logs this but only if `--log-dir` is set.

**ISSUE 6.4: Download errors go to logger only**
- `logger.error(...)` on download failure. With progress bar, error messages get visually lost.

**ISSUE 6.5: `discover` command doesn't handle empty results**
- Returns "Discovered 0 stations" with no warning. Confusing but not data-losing.

---

## Summary — Critical Issues (ranked)

1. **Extract crashes on corrupt/empty/password-protected PDFs** (2.1-2.3) — Stops all extraction.
2. **Partial line item extraction with no visibility** (4.3) — Spend can be wildly inaccurate.
3. **Orphan line items invisible to queries** (4.4) — Money is spent but unattributed.
4. **Concurrent extract creates duplicate rows** (3.1) — Silent data duplication.
5. **`get_file_history` silently returns empty** (1.3) — Whole stations appear to have no files.
6. **`requests.Session` shared across threads** (5.1) — Intermittent connection errors.
7. **T&C misclassification** (4.2) — False positives skip valid pages.
8. **No re-extract mechanism** (4.6) — Can't re-process after fixing bugs.
9. **Read-only DB blocks read-only commands** (3.3) — Schema init runs on every connection.
10. **Extract quality invisible without --log-dir** (6.2, 6.3) — No reporting on completeness.
