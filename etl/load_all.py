"""Download (if needed) and load every dataset:  python -m etl.load_all [--refresh]"""

import argparse
import sys
from datetime import UTC, datetime

import psycopg

from etl import socrata
from etl.load import TABLES, create_schema, database_url, load_table

STALE_AFTER_DAYS = 365


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="re-download datasets even if cached in etl/data/raw")
    args = ap.parse_args(argv)

    with psycopg.connect(database_url(), autocommit=True) as conn:
        create_schema(conn)
        for spec in TABLES:
            cached = (socrata.RAW_DIR / f"{spec.dataset_id}.json").exists()
            if args.refresh or not cached:
                print(f"Downloading {spec.dataset_id} ...")
                socrata.download(spec.dataset_id)
            meta = socrata.read_meta(spec.dataset_id)
            report = load_table(conn, spec, socrata.read_rows(spec.dataset_id))

            print(f"{spec.table:20s} {report.loaded:5d} rows  (source {spec.dataset_id}, "
                  f"fetched {meta['fetched_at'][:10]})")
            for reason, n in report.skipped.items():
                print(f"{'':20s} {n:5d} marked unusable: {reason}")
            if report.repaired:
                print(f"{'':20s} {report.repaired:5d} invalid polygons repaired (flagged geom_was_invalid)")
            for reason, n in report.rejected.items():
                print(f"{'':20s} {n:5d} REJECTED: {reason}")
            if meta["data_updated_at"]:
                age = (datetime.now(UTC) - datetime.fromisoformat(meta["data_updated_at"])).days
                if age > STALE_AFTER_DAYS:
                    print(f"{'':20s} WARNING: publisher last updated this dataset {age} days ago "
                          f"({meta['data_updated_at'][:10]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
