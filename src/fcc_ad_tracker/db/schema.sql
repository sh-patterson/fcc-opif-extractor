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
    file_type TEXT DEFAULT 'unknown'
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

CREATE TABLE IF NOT EXISTS contracts (
    contract_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES stations(entity_id),
    contract_number TEXT NOT NULL,
    advertiser TEXT,
    candidate TEXT,
    agency TEXT,
    contract_start TEXT,
    contract_end TEXT,
    total_spots INTEGER,
    gross_total REAL,
    agency_commission REAL,
    net_total REAL,
    demographic TEXT,
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
    extracted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_entity ON files(entity_id);
CREATE INDEX IF NOT EXISTS idx_extractions_file ON extractions(file_id);
CREATE INDEX IF NOT EXISTS idx_extractions_field ON extractions(field_name);
CREATE INDEX IF NOT EXISTS idx_contracts_entity ON contracts(entity_id);
CREATE INDEX IF NOT EXISTS idx_contracts_number ON contracts(contract_number);
CREATE INDEX IF NOT EXISTS idx_line_items_file ON line_items(file_id);
CREATE INDEX IF NOT EXISTS idx_line_items_contract ON line_items(contract_number);

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
