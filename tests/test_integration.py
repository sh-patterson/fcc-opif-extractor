"""End-to-end: discover -> download -> extract -> query with mocked API + synthetic PDFs."""
import sqlite3


import pytest
import responses

from fcc_ad_tracker.config import OpifConfig
from fcc_ad_tracker.client import OpifClient
from fcc_ad_tracker.db.connection import init_schema
from fcc_ad_tracker.db import queries
from fcc_ad_tracker.discover import discover_stations
from fcc_ad_tracker.download import download_pdf, find_political_folder, walk_folder_tree
from fcc_ad_tracker.extract import extract_pdf_text
from fcc_ad_tracker.fields import extract_all_fields


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


@responses.activate
def test_full_pipeline(db, text_pdf, tmp_path):
    cfg = OpifConfig(rate_limit_delay=0.0, retry_jitter_max=0.0)
    client = OpifClient(cfg)

    # 1. Discovery
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/service/tv/facility/search/CA.json",
        json={
            "status": "OK",
            "results": {
                "searchList": [
                    {
                        "searchType": "State",
                        "facility": None,
                        "facilityList": [
                            {
                                "id": 1,
                                "callSign": "KABC-TV",
                                "community": {"city": "LOS ANGELES", "state": "CA"},
                                "nielsenDma": "LOS ANGELES",
                                "service": "Full Service",
                            },
                        ],
                    }
                ]
            },
        },
    )
    stations = discover_stations(client, state="CA", target_dmas=["LOS ANGELES"])
    assert len(stations) == 1
    s = stations[0]
    queries.upsert_station(
        db, s.entity_id, s.call_sign, s.market, s.city, s.state, s.service_type
    )

    # 2. Folder traversal
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/folder/parentFolders.json",
        json={
            "status": "success",
            "results": {
                "subFolders": [
                    {
                        "id": "pol-folder",
                        "folderName": "Political Files",
                        "subFolderCount": 0,
                        "fileCount": 1,
                    }
                ],
                "files": [],
            },
        },
    )
    folder_id = find_political_folder(client, s.entity_id)
    assert folder_id == "pol-folder"

    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/folder/id/pol-folder.json",
        json={
            "status": "success",
            "results": {
                "subFolders": [],
                "files": [
                    {
                        "id": "file-1",
                        "fileName": "order.pdf",
                        "fileManagerId": "fm-1",
                        "fileSize": 1024,
                        "folder": {"id": "pol-folder"},
                    }
                ],
            },
        },
    )
    files = walk_folder_tree(client, folder_id, s.entity_id)
    assert len(files) == 1

    # 3. Download (use synthetic text_pdf as content)
    pdf_content = text_pdf.read_bytes()
    responses.add(
        responses.GET,
        f"{cfg.base_url}/api/manager/download/pol-folder/fm-1.pdf",
        status=302,
        headers={"Location": "https://files.fcc.gov/test.pdf"},
    )
    responses.add(responses.GET, "https://files.fcc.gov/test.pdf", body=pdf_content)

    dest = tmp_path / "KABC-TV" / "fm-1.pdf"
    download_pdf(client, "pol-folder", "fm-1", dest)
    assert dest.exists()

    queries.upsert_file(
        db,
        file_id="file-1",
        entity_id="1",
        file_manager_id="fm-1",
        file_name="order.pdf",
        folder_id="pol-folder",
        file_size=1024,
    )
    queries.mark_downloaded(db, "file-1", sha256="abc", local_path=str(dest))

    # 4. Extract text
    result = extract_pdf_text(dest)
    assert result.has_text is True

    # 5. Extract fields
    for page_num, page_text in enumerate(result.pages):
        matches = extract_all_fields(page_text, page=page_num)
        for m in matches:
            queries.insert_extraction(
                db,
                file_id="file-1",
                field_name=m.field_name,
                field_value=m.value,
                confidence=m.confidence,
                page_number=m.page_number,
            )

    # 6. Query
    results = queries.query_extractions(db, field_name="advertiser")
    assert len(results) >= 1
    assert any("ACME" in r["field_value"] for r in results)

    results = queries.query_extractions(db, field_name="candidate")
    assert len(results) >= 1
