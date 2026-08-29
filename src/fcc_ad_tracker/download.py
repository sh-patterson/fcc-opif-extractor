import hashlib
import logging
from pathlib import Path

from fcc_ad_tracker.client import OpifClient

logger = logging.getLogger(__name__)


def find_political_folder(client: OpifClient, entity_id: str) -> str | None:
    """Find the 'Political Files' folder from parent folders. Returns folder ID or None."""
    data = client.get_parent_folders(entity_id)
    # Live API uses "folders" with "folder_name" / "entity_folder_id"
    for folder in data.get("folders", []):
        if "political" in folder.get("folder_name", "").lower():
            return folder["entity_folder_id"]
    # Fallback: fixture/test shape uses "results.subFolders" with "folderName" / "id"
    for folder in data.get("results", {}).get("subFolders", []):
        if "political" in folder.get("folderName", "").lower():
            return folder["id"]
    return None


def walk_folder_tree(client: OpifClient, folder_id: str, entity_id: str) -> list[dict]:
    """Recursively walk folder tree, collecting all file entries."""
    data = client.get_folder(folder_id, entity_id)
    results = data.get("results", {})
    files = list(results.get("files", []))
    for sub in results.get("subFolders", []):
        files.extend(walk_folder_tree(client, sub["id"], entity_id))
    return files


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_pdf(client: OpifClient, file_manager_id: str, dest: Path) -> Path:
    """Download a PDF via the client's download URL resolution. Returns dest path."""
    url = client.get_download_url(file_manager_id)
    content = client.download_bytes(url, timeout=60)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest
