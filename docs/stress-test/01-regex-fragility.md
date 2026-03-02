# Regex Fragility Audit

**Date:** 2026-03-01
**Scope:** All regex patterns in contracts.py, line_items.py, fields.py, classify.py

---

## FILE: `line_items.py`

### 1. `_LINE_ITEM_RE` — The Main Line-Item Parser
**Fragility: HIGH**

This is a single monolithic regex that must match 11 capture groups in sequence. Any deviation in any field causes a total-line miss (silent data loss, not an error).

**What it currently handles:**
- `N <digits> <CHANNEL> <MM/DD/YY> <MM/DD/YY> <show> <time> <:len> <$rate> <type> <spots> <$total>`
- Time slots: `5:00A-5:30A`, `4p-5p`, `6p-630p`, `various`
- Spot lengths: `:30`, `:15`, `:15/:15`
- Rate types: `NM`, `BK`, `CDR`
- Optional PCode `CDR` before rate type
- Optional duplicate time column
- Optional rate per spot (dollar amount)

**Concrete inputs that BREAK it:**

1. **"N" line marker is WideOrbit-specific.** Non-WideOrbit traffic systems may use different line prefixes or no prefix at all:
   - `L 58 KABC 03/03/26 ...` — fails (no "N" anchor)
   - `58 KABC 03/03/26 ...` — fails (no letter prefix)
   - `  1. KABC 03/03/26 ...` — fails (numbered list format)

2. **Channel code length:** `[A-Z]{3,5}` rejects valid 2-letter or 6+ letter identifiers:
   - `N 1 KQ 03/03/26 ...` — fails (2-letter)
   - `N 1 KABC-TV 03/03/26 ...` — fails (hyphen in call sign)
   - `N 1 KTTV-CD 03/03/26 ...` — fails (suffix)

3. **Full 12-hour time formats with spaces/colons around AM/PM:**
   - `N 1 KABC 03/03/26 03/07/26 News 9:00 PM-11:01 PM :30 $500 NM 5 $2,500` — **FAILS** (space before PM, full "PM" not just "p")
   - `N 1 KABC 03/03/26 03/07/26 News 9:00PM-11:01PM :30 $500 NM 5 $2,500` — **FAILS** ("PM" not just "P")
   - The time regex `\d+(?::\d{2})?[apAP]` only matches a SINGLE letter (a/p/A/P), not "AM"/"PM"

4. **"Various" capitalization:** The regex has `|various` (lowercase only). Test input:
   - `N 1 KABC 03/03/26 03/07/26 NBA Lakers Various :30 $25000 NM 1 $25000` — **FAILS** (capital V)
   - `N 1 KABC 03/03/26 03/07/26 NBA Lakers VARIOUS :30 $25000 NM 1 $25000` — **FAILS** (all caps)

5. **Time ranges with "GMA M-F 7-8a" compact show+day+time format:**
   - `N 1 KABC 03/03/26 03/07/26 GMA M-F 7a-8a :30 $500 NM 5 $2500` — might work since `7a-8a` matches the time regex, but "M-F" in show name could confuse greedy capture
   - `N 1 KABC 03/03/26 03/07/26 GMA M-F 7-8a :30 $500 NM 5 $2500` — **FAILS**: `7-8a` doesn't match `\d+(?::\d{2})?[apAP]-\d+(?::\d{2})?[apAP]` because the start time has no am/pm suffix

6. **"Sat 4-5p" day-prefixed time:**
   - `N 1 KABC 03/03/26 03/07/26 News Sat 4p-5p :30 $500 NM 5 $2500` — "Sat" becomes part of show name, this probably works
   - `N 1 KABC 03/03/26 03/07/26 News Sa 4-5p :30 $500 NM 5 $2500` — **FAILS**: `4-5p` only has am/pm on end time

7. **Dollar amounts with leading $ or without:**
   - Negative amounts: `($500)` or `-$500` for credits — **FAILS** (no negative/paren handling in rate or total)
   - Zero amounts: `$0.00` — works for regex but 0.0 may be semantically wrong

8. **4-digit dates (MM/DD/YYYY):**
   - `N 1 KABC 03/03/2026 03/07/2026 News 5p-6p :30 $500 NM 5 $2500` — works (regex has `\d{2,4}` for year)

9. **Show names with numbers that look like time slots:**
   - `N 1 KABC 03/03/26 03/07/26 2020 7p-8p :30 $500 NM 5 $2500` — might fail, "2020" could be parsed ambiguously
   - `N 1 KABC 03/03/26 03/07/26 48 Hours 8p-9p :30 $500 NM 5 $2500` — same risk

10. **Rate types beyond NM/BK/CDR:**
    - Other traffic systems may use: `FX`, `PR`, `ROS`, `TAP`, `BUMP` — all would **FAIL** since only `NM|BK|CDR` is matched

11. **Spot lengths beyond :15 and :30:**
    - `:60` (one-minute spots) — works (regex is `:\d{2}`)
    - `:05` (five-second IDs) — works
    - `:120` — **FAILS** (3 digits after colon, regex requires exactly 2)

### 2. `_WEEK_RE` — Week Breakdown Parser
**Fragility: MEDIUM**

**What it handles:** `Week: MM/DD/YY MM/DD/YY -1111-- <spots> $<rate>`

**Breakage inputs:**
- Day pattern with other characters: `Week: 03/03/26 03/08/26 SMTWTFS 5 $500` — **FAILS** (pattern requires exactly `[-1]{7}`)
- Some systems use `X` instead of `1`: `Week: 03/03/26 03/08/26 -XXXXX-- 5 $500` — **FAILS**
- The `[-1]{7}` is oddly specific. Would break on any other day encoding scheme

---

## FILE: `contracts.py`

### 3. `extract_contract_number` — Contract Number Extraction
**Fragility: MEDIUM**

**What it handles:**
- `Contract: 424082`, `Contract #729823`, `Contract: 424082-New`
- WideOrbit format: `424880 / WOC15574999` (number on own line)
- Underscore: `TomSteyer_1474031_Rev1`

**Breakage inputs:**
- **8-digit contract numbers:** `Contract: 12345678` — **FAILS** (regex caps at 7 digits: `\d{5,7}`)
- **4-digit contract numbers:** `Contract: 1234` — **FAILS** (min 5 digits)
- **Alpha-numeric contract IDs:** `Contract: WO-424082` — **FAILS** (expects pure digits)
- **"Order" instead of "Contract":** `Order: 424082` or `Order #424082` — **FAILS** (only matches "contract" keyword)
- **Non-WideOrbit line format:** `424880 - WOC15574999` (hyphen not slash) — **FAILS** on the WideOrbit pattern (requires ` / `)

### 4. `extract_revision` — Revision Number Extraction
**Fragility: LOW**

**What it handles:** `Rev 1`, `Rev. 1`, `_Rev1`, `--3`, `REVISION 2`

**Breakage inputs:**
- `Version 2` — **FAILS**
- `V2` or `v2` — **FAILS**
- `Amendment 1` — **FAILS**

These are mostly unlikely for FCC filings, so low risk.

### 5. `extract_contract_dates` — Date Range Extraction
**Fragility: MEDIUM**

**What it handles:**
- `Contract Dates: 02/23/2026 - 03/09/2026`
- WideOrbit format with dates on next line after "Contract Dates" header

**Breakage inputs:**
- **ISO format dates:** `Contract Dates: 2026-02-23 - 2026-03-09` — **FAILS**
- **Dash-separated dates:** `Contract Dates: 02-23-2026 - 03-09-2026` — **FAILS**
- **"thru" or "to" instead of dash:** `Contract Dates: 02/23/2026 thru 03/09/2026` — **FAILS**
- **"Flight Dates:" label:** `Flight Dates: 02/23/2026 - 03/09/2026` — **FAILS** (contracts.py only matches "contract" keyword; fields.py handles "Flight Dates:" separately)

### 6. `extract_agency` — Agency Extraction
**Fragility: LOW**

**Breakage:** `Agency  BUYER'S EDGE MEDIA LLC` (no colon) — **FAILS**. Low risk.

### 7. `extract_demographics` — Demographics Extraction
**Fragility: LOW-MEDIUM**

Potential issue: `Demo:` label — **FAILS** (only matches "demographic")

### 8. `_parse_dollar` (contracts.py) — Dollar Parsing
**Fragility: MEDIUM**

**BUG:** Parenthesized amounts `($78,405.00)` are conventionally negative but return **positive** 78405.0. The `strip("()")` removes parens but doesn't negate. `agency_commission` gets wrong sign.

Other breakage:
- Empty string: `""` → `float("")` → **RAISES ValueError**, not caught
- Non-numeric: `"N/A"` or `"TBD"` → **RAISES ValueError**, not caught

### 9. `extract_contract_totals` — Totals Block Extraction
**Fragility: MEDIUM**

**Breakage:**
- `Total  227  $522,700.00` (singular, no "s") — **FAILS**
- `Grand Total  227  $522,700.00` — **FAILS**
- **Spots with commas:** `Totals  1,227  $522,700.00` — **FAILS** (`\d+` doesn't allow commas)

---

## FILE: `fields.py`

### 10. `extract_advertiser` / `extract_candidate`
**Fragility: MEDIUM**

**Breakage for the "FOR OFFICE" pattern:**
- `JOHN SMITH FOR PRESIDENT 2026` — **FAILS** ("PRESIDENT" not in list)
- `SMITH FOR U.S. SENATE 2026` — **FAILS** ("U.S. SENATE" has period and space)
- `CITIZENS TO ELECT SMITH` — **FAILS** (different naming convention)
- **Hyphenated names:** `MARTINEZ-GARCIA FOR CONGRESS` — **FAILS** (no hyphens in char class)

---

## FILE: `classify.py`

### 11. `is_terms_and_conditions`
**Fragility: LOW**

Only checks first 200 chars. False positives (contract page starting with "STANDARD TERMS") would skip the page silently.

### 12. `classify_file_type`
**Fragility: LOW**

The `\d{5,7}` fallback is aggressive — any filename with a 5-7 digit number gets "contract" classification.

---

## Summary — Top Risks by Priority

| # | Pattern | File | Fragility | Biggest Risk |
|---|---------|------|-----------|-------------|
| 1 | `_LINE_ITEM_RE` | line_items.py | **HIGH** | "AM/PM" vs "a/p" single-char assumption; "Various" case-sensitivity; "N" prefix assumption; silent total miss on any deviation |
| 2 | `_LINE_ITEM_RE` time slot | line_items.py | **HIGH** | `9:00 PM-11:01 PM` format completely breaks the time regex |
| 3 | `_parse_dollar` sign handling | contracts.py | **MEDIUM** | Parenthesized negatives silently become positive; empty/non-numeric strings crash |
| 4 | `extract_contract_number` | contracts.py | **MEDIUM** | 8+ digit contract numbers, alpha-prefix IDs, non-"Contract" labels |
| 5 | `extract_contract_totals` | contracts.py | **MEDIUM** | Requires literal "totals" with the "s"; spots with commas fail |
| 6 | `_LINE_ITEM_RE` rate types | line_items.py | **MEDIUM** | Only NM/BK/CDR — any other system's rate codes silently drop lines |
| 7 | Date format rigidity | contracts.py, fields.py | **MEDIUM** | Only MM/DD/YY(YY) with slashes |
| 8 | `extract_advertiser`/`extract_candidate` | fields.py | **MEDIUM** | Hyphenated names, offices not in list, case sensitivity |

## Recommendations

1. **Make `_LINE_ITEM_RE` case-insensitive for "various"** — trivial fix
2. **Expand time slot regex to handle "AM"/"PM" (two chars) with optional space** — highest-impact fix for cross-station compatibility
3. **Add a sign-aware `_parse_dollar`** that treats `(...)` as negative
4. **Consider making the "N" line prefix configurable or optional** for non-WideOrbit systems
5. **Expand rate types** — at minimum add a catch-all `[A-Z]{2,3}` option
6. **Add `:60` and longer spot lengths** — `:\d{2,3}` instead of `:\d{2}`
7. **The biggest structural risk is silent failure.** When `_LINE_ITEM_RE` doesn't match, the line is simply skipped with no logging. Consider a two-pass approach: first pass with strict regex, second pass with looser pattern that logs warnings for near-misses.
