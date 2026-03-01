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
    ocr_done INTEGER DEFAULT 0
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

CREATE INDEX IF NOT EXISTS idx_files_entity ON files(entity_id);
CREATE INDEX IF NOT EXISTS idx_extractions_file ON extractions(file_id);
CREATE INDEX IF NOT EXISTS idx_extractions_field ON extractions(field_name);
