"""Download NYC Open Data (Socrata) datasets to local JSON, so the load step can be re-run offline."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE_URL = "https://data.cityofnewyork.us"
PAGE_SIZE = 5000
RAW_DIR = Path(__file__).parent / "data" / "raw"


def fetch_rows(dataset_id: str, client: httpx.Client, page_size: int = PAGE_SIZE) -> list[dict]:
    rows: list[dict] = []
    while True:
        resp = client.get(
            f"{BASE_URL}/resource/{dataset_id}.json",
            params={
                "$select": ":*,*",  # include :id and :updated_at for row-level provenance
                "$limit": page_size,
                "$offset": len(rows),
                "$order": ":id",
            },
        )
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < page_size:
            return rows


def fetch_data_updated_at(dataset_id: str, client: httpx.Client) -> str | None:
    """When the publisher last changed the data (not when we fetched it)."""
    resp = client.get(f"{BASE_URL}/api/views/{dataset_id}.json")
    resp.raise_for_status()
    ts = resp.json().get("rowsUpdatedAt")
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts else None


def download(dataset_id: str, raw_dir: Path = RAW_DIR, client: httpx.Client | None = None) -> Path:
    """Fetch a dataset into raw_dir/<id>.json plus a <id>.meta.json provenance sidecar."""
    owns_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        rows = fetch_rows(dataset_id, client)
        updated_at = fetch_data_updated_at(dataset_id, client)
    finally:
        if owns_client:
            client.close()
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{dataset_id}.json"
    path.write_text(json.dumps(rows))
    (raw_dir / f"{dataset_id}.meta.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "fetched_at": datetime.now(UTC).isoformat(),
                "data_updated_at": updated_at,
                "row_count": len(rows),
            },
            indent=2,
        )
    )
    return path


def read_meta(dataset_id: str, raw_dir: Path = RAW_DIR) -> dict:
    return json.loads((raw_dir / f"{dataset_id}.meta.json").read_text())


def read_rows(dataset_id: str, raw_dir: Path = RAW_DIR) -> list[dict]:
    return json.loads((raw_dir / f"{dataset_id}.json").read_text())
