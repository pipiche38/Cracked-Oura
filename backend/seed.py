"""
Seed / one-shot ingest from a directory of Oura CSV exports.

Usage
-----
  python -m backend.seed                          # ingest data/App Data, seed default dashboard
  python -m backend.seed --data-dir /path/to/dir
  python -m backend.seed --reset                  # wipe DB first
  python -m backend.seed --skip-dashboard         # ingest only, no dashboard config
  python -m backend.seed --force-dashboard        # overwrite existing dashboard config
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import List, Optional

# Locate project root (backend/ lives one level below repo root)
PROJECT_ROOT = pathlib.Path(__file__).parent.parent

DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "App Data"

DEFAULT_DASHBOARD: dict = {
    "widgets": [
        {"id": "w1", "type": "trend", "title": "Sleep Score", "path": "sleep.score", "span": 2},
        {"id": "w2", "type": "trend", "title": "Readiness Score", "path": "readiness.score", "span": 2},
        {"id": "w3", "type": "trend", "title": "Activity Score", "path": "activity.score", "span": 2},
        {"id": "w4", "type": "stat", "title": "Steps", "path": "activity.steps", "span": 1},
        {"id": "w5", "type": "stat", "title": "Avg HRV", "path": "sleep_session.average_hrv", "span": 1},
        {"id": "w6", "type": "stat", "title": "Resting HR", "path": "sleep_session.lowest_heart_rate", "span": 1},
    ]
}


def reset_database() -> None:
    from backend.src.database import engine
    from backend.src.models import Base

    print("Dropping all tables…")
    Base.metadata.drop_all(bind=engine)
    print("Recreating schema…")
    Base.metadata.create_all(bind=engine)
    print("Database reset complete.")


def seed_dashboard_config(force: bool = False) -> None:
    from backend.src.config import config_manager

    cfg = config_manager.get_config()
    existing = cfg.get("dashboard_layout")
    if existing and not force:
        print("Dashboard config already exists — skipping (use --force-dashboard to overwrite).")
        return

    config_manager.update_config(dashboard_layout=json.dumps(DEFAULT_DASHBOARD))
    print("Default dashboard config written.")


def ingest_directory(data_dir: pathlib.Path) -> None:
    from backend.src.database import SessionLocal, init_db
    from backend.src.ingestion import OuraParser

    if not data_dir.exists():
        print(f"[WARN] Data directory not found: {data_dir}", file=sys.stderr)
        return

    csv_files: List[pathlib.Path] = sorted(data_dir.rglob("*.csv"))
    if not csv_files:
        print(f"[WARN] No CSV files found in {data_dir}", file=sys.stderr)
        return

    print(f"Ingesting {len(csv_files)} CSV file(s) from {data_dir}…")
    init_db()
    db = SessionLocal()
    try:
        parser = OuraParser(db)
        parser.parse_directory(str(data_dir))
        print(f"Ingestion complete.")
    except Exception as exc:
        print(f"[ERROR] Ingestion failed: {exc}", file=sys.stderr)
    finally:
        db.close()


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Seed Oura database from CSV exports.")
    parser.add_argument("--data-dir", type=pathlib.Path, default=DEFAULT_DATA_DIR,
                        help="Directory containing Oura CSV exports (default: data/App Data)")
    parser.add_argument("--reset", action="store_true",
                        help="Drop and recreate all tables before ingesting")
    parser.add_argument("--skip-dashboard", action="store_true",
                        help="Do not write default dashboard configuration")
    parser.add_argument("--force-dashboard", action="store_true",
                        help="Overwrite existing dashboard configuration")
    args = parser.parse_args(argv)

    if args.reset:
        reset_database()
    else:
        from backend.src.database import init_db
        init_db()

    ingest_directory(args.data_dir)

    if not args.skip_dashboard:
        seed_dashboard_config(force=args.force_dashboard)

    print("Done.")


if __name__ == "__main__":
    main()
