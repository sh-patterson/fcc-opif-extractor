CREATE TABLE IF NOT EXISTS stations (
    entity_id TEXT PRIMARY KEY,
    call_sign TEXT NOT NULL,
    market TEXT,
    city TEXT,
    state TEXT,
    service_type TEXT
);

CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES stations(entity_id),
    file_manager_id TEXT,
    file_name TEXT,
    folder_id TEXT,
    folder_path TEXT,
    file_size INTEGER,
    sha256 TEXT,
    downloaded_at TEXT,
    local_path TEXT,
    ocr_needed INTEGER DEFAULT 0,
    ocr_done INTEGER DEFAULT 0,
    file_type TEXT DEFAULT 'unknown',
    extraction_status TEXT DEFAULT 'pending',
    create_ts TEXT,
    last_update_ts TEXT,
    history_status TEXT
);

CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL REFERENCES files(file_id),
    field_name TEXT NOT NULL,
    field_value TEXT NOT NULL,
    confidence TEXT NOT NULL,
    page_number INTEGER DEFAULT 0,
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    office_sought TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS candidate_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL UNIQUE,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    contract_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES stations(entity_id),
    contract_number TEXT NOT NULL,
    advertiser TEXT,
    candidate TEXT,
    candidate_id INTEGER REFERENCES candidates(id),
    office_sought TEXT,
    agency TEXT,
    contract_start TEXT,
    contract_end TEXT,
    total_spots INTEGER,
    gross_total REAL,
    agency_commission REAL,
    net_total REAL,
    demographic TEXT,
    extraction_method TEXT,
    revision_number INTEGER DEFAULT 0,
    latest_file_id TEXT REFERENCES files(file_id),
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL REFERENCES files(file_id),
    contract_number TEXT,
    line_number INTEGER,
    channel TEXT,
    show_name TEXT,
    time_slot TEXT,
    spot_length TEXT,
    rate_type TEXT,
    spots INTEGER,
    rate_per_spot REAL,
    line_total REAL,
    start_date TEXT,
    end_date TEXT,
    page_number INTEGER,
    extracted_at TEXT,
    extraction_method TEXT
);

CREATE TABLE IF NOT EXISTS line_item_weeks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL REFERENCES files(file_id),
    contract_number TEXT,
    page_number INTEGER,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    day_pattern TEXT,
    spots INTEGER,
    rate REAL,
    extracted_at TEXT,
    extraction_method TEXT
);

CREATE TABLE IF NOT EXISTS rss_items (
    guid TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES stations(entity_id),
    call_sign TEXT,
    title TEXT,
    link TEXT,
    published_at TEXT,
    seen_at TEXT,
    raw_xml TEXT
);

CREATE TABLE IF NOT EXISTS nab_forms (
    file_id TEXT PRIMARY KEY REFERENCES files(file_id),
    entity_id TEXT REFERENCES stations(entity_id),
    form_type TEXT,
    candidate_name TEXT,
    office_sought TEXT,
    party_affiliation TEXT,
    election_level TEXT,
    raw_text TEXT,
    extracted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_entity ON files(entity_id);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_downloaded_at ON files(downloaded_at);
CREATE INDEX IF NOT EXISTS idx_extractions_file ON extractions(file_id);
CREATE INDEX IF NOT EXISTS idx_extractions_field ON extractions(field_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_extractions_dedupe
    ON extractions(file_id, field_name, field_value, confidence, page_number);
CREATE INDEX IF NOT EXISTS idx_candidates_name ON candidates(canonical_name);
CREATE INDEX IF NOT EXISTS idx_candidate_aliases_name ON candidate_aliases(alias_name);
CREATE INDEX IF NOT EXISTS idx_contracts_entity ON contracts(entity_id);
CREATE INDEX IF NOT EXISTS idx_contracts_number ON contracts(contract_number);
CREATE INDEX IF NOT EXISTS idx_contracts_entity_number ON contracts(entity_id, contract_number);
CREATE INDEX IF NOT EXISTS idx_line_items_file ON line_items(file_id);
CREATE INDEX IF NOT EXISTS idx_line_items_contract ON line_items(contract_number);
CREATE INDEX IF NOT EXISTS idx_line_item_weeks_file ON line_item_weeks(file_id);
CREATE INDEX IF NOT EXISTS idx_line_item_weeks_contract ON line_item_weeks(contract_number);
CREATE INDEX IF NOT EXISTS idx_rss_items_entity ON rss_items(entity_id);
CREATE INDEX IF NOT EXISTS idx_rss_items_seen_at ON rss_items(seen_at);
CREATE INDEX IF NOT EXISTS idx_nab_forms_candidate ON nab_forms(candidate_name);
CREATE INDEX IF NOT EXISTS idx_nab_forms_office ON nab_forms(office_sought);
CREATE UNIQUE INDEX IF NOT EXISTS uq_line_items_dedupe ON line_items(
    file_id,
    COALESCE(contract_number, ''),
    COALESCE(line_number, -1),
    COALESCE(channel, ''),
    COALESCE(show_name, ''),
    COALESCE(time_slot, ''),
    COALESCE(spot_length, ''),
    COALESCE(rate_type, ''),
    COALESCE(spots, -1),
    COALESCE(rate_per_spot, -1),
    COALESCE(line_total, -1),
    COALESCE(start_date, ''),
    COALESCE(end_date, ''),
    COALESCE(page_number, -1)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_line_item_weeks_dedupe ON line_item_weeks(
    file_id,
    COALESCE(contract_number, ''),
    COALESCE(page_number, -1),
    start_date,
    end_date,
    COALESCE(day_pattern, ''),
    COALESCE(spots, -1),
    COALESCE(rate, -1)
);

-- District-to-DMA crosswalk data from The Downballot
-- https://www.thedownballot.com
CREATE TABLE IF NOT EXISTS dma_districts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    district TEXT NOT NULL,     -- 'CA-27', 'TX-22', etc.
    dma_name TEXT NOT NULL,     -- 'Los Angeles' (from Downballot CSV)
    fcc_market TEXT,            -- 'LOS ANGELES' (auto-matched to stations.market)
    state TEXT NOT NULL,
    population INTEGER,
    weight REAL NOT NULL        -- 0.0-1.0 (percentage / 100)
);
CREATE INDEX IF NOT EXISTS idx_dma_districts_district ON dma_districts(district);
CREATE INDEX IF NOT EXISTS idx_dma_districts_market ON dma_districts(fcc_market);
