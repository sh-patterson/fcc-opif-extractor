import hashlib
from unittest.mock import MagicMock

import responses

from fcc_ad_tracker.download import (
    download_pdf,
    find_political_folder,
    sha256_file,
    walk_folder_tree,
)


def test_find_political_folder_success():
    client = MagicMock()
    client.get_parent_folders.return_value = {
        "status": "success",
        "results": {
            "subFolders": [
                {"id": "other-folder", "folderName": "Letters and Emails"},
                {"id": "pol-folder-123", "folderName": "Political Files"},
            ],
        },
    }
    result = find_political_folder(client, "25452")
    assert result == "pol-folder-123"
    client.get_parent_folders.assert_called_once_with("25452")


def test_find_political_folder_not_found():
    client = MagicMock()
    client.get_parent_folders.return_value = {
        "status": "success",
        "results": {
            "subFolders": [
                {"id": "other-folder", "folderName": "Letters and Emails"},
            ],
        },
    }
    result = find_political_folder(client, "25452")
    assert result is None


def test_walk_folder_tree_collects_files():
    """Walk a tree with subfolders and files at multiple levels."""
    client = MagicMock()
    # Root folder has one subfolder and one file
    client.get_folder.side_effect = [
        {
            "status": "success",
            "results": {
                "id": "root",
                "subFolders": [
                    {"id": "sub-1", "folderName": "2026", "subFolderCount": 1, "fileCount": 0},
                ],
                "files": [
                    {"id": "f1", "fileName": "root_file.pdf", "fileManagerId": "fm-1"},
                ],
            },
        },
        # sub-1 has no subfolders, one file
        {
            "status": "success",
            "results": {
                "id": "sub-1",
                "subFolders": [],
                "files": [
                    {"id": "f2", "fileName": "sub_file.pdf", "fileManagerId": "fm-2"},
                ],
            },
        },
    ]
    files = walk_folder_tree(client, "root", "25452")
    assert len(files) == 2
    names = [f["fileName"] for f in files]
    assert "root_file.pdf" in names
    assert "sub_file.pdf" in names


def test_sha256_file(tmp_path):
    path = tmp_path / "test.txt"
    path.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert sha256_file(path) == expected


@responses.activate
def test_download_pdf(tmp_path):
    client = MagicMock()
    download_url = "https://files.fcc.gov/some/path.pdf"
    client.get_download_url.return_value = download_url
    pdf_content = b"%PDF-1.4 fake pdf content"
    client.download_bytes.return_value = pdf_content

    dest = tmp_path / "output.pdf"
    result = download_pdf(client, "file-123", dest)
    assert result == dest
    assert dest.read_bytes() == pdf_content
    client.get_download_url.assert_called_once_with("file-123")
    client.download_bytes.assert_called_once_with(download_url, timeout=60)
