from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.kobis_reader import read_kobis_files


RAW_COLUMNS = [
    "source_file",
    "period_start",
    "period_end",
    "loaded_at",
    "row_number_in_file",
    "rank",
    "movie_name",
    "movie_name_clean",
    "release_date",
    "sales_amount",
    "sales_share",
    "cumulative_sales_amount",
    "audience_count",
    "cumulative_audience",
    "screen_count",
    "show_count",
    "primary_country",
    "country",
    "production_company",
    "distributor",
    "rating",
    "genre",
    "director",
    "actors",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SQLite DB from KOBIS period boxoffice files.")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--db-path", type=Path, default=ROOT / "data" / "db" / "kobis_movies.db")
    args = parser.parse_args()

    raw_files = sorted(
        path for path in args.raw_dir.iterdir() if path.suffix.lower() in {".xls", ".xlsx"}
    )
    if not raw_files:
        raise SystemExit(f"No KOBIS files found in {args.raw_dir}")

    loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = read_kobis_files(raw_files)
    for record in records:
        record["loaded_at"] = loaded_at

    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    if args.db_path.exists():
        args.db_path.unlink()

    with sqlite3.connect(args.db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        create_schema(conn)
        insert_raw(conn, records)
        build_snapshot(conn)
        build_snapshot_selected(conn)
        conn.execute("VACUUM")

    print(f"Built {args.db_path}")
    print(f"Raw rows: {len(records):,}")


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE boxoffice_period_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            loaded_at TEXT NOT NULL,
            row_number_in_file INTEGER NOT NULL,
            rank INTEGER,
            movie_name TEXT,
            movie_name_clean TEXT,
            release_date TEXT,
            sales_amount INTEGER,
            sales_share REAL,
            cumulative_sales_amount INTEGER,
            audience_count INTEGER,
            cumulative_audience INTEGER,
            screen_count INTEGER,
            show_count INTEGER,
            primary_country TEXT,
            country TEXT,
            production_company TEXT,
            distributor TEXT,
            rating TEXT,
            genre TEXT,
            director TEXT,
            actors TEXT
        );

        CREATE INDEX idx_raw_movie_release
            ON boxoffice_period_raw (movie_name_clean, release_date);

        CREATE INDEX idx_raw_period_end
            ON boxoffice_period_raw (period_end);
        """
    )


def insert_raw(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> None:
    placeholders = ", ".join(["?"] * len(RAW_COLUMNS))
    columns = ", ".join(RAW_COLUMNS)
    values = [[record.get(column) for column in RAW_COLUMNS] for record in records]
    conn.executemany(
        f"INSERT INTO boxoffice_period_raw ({columns}) VALUES ({placeholders})",
        values,
    )


def build_snapshot(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE movie_snapshot AS
        WITH final_audience AS (
            SELECT
                movie_name_clean,
                release_date,
                MAX(cumulative_audience) AS target_final_audience
            FROM boxoffice_period_raw
            GROUP BY movie_name_clean, release_date
        ),
        ranked AS (
            SELECT
                raw.*,
                fa.target_final_audience,
                ROW_NUMBER() OVER (
                    PARTITION BY raw.movie_name_clean, raw.release_date
                    ORDER BY
                        raw.period_end DESC,
                        raw.cumulative_audience DESC,
                        raw.source_file ASC,
                        raw.row_number_in_file ASC
                ) AS snapshot_rank
            FROM boxoffice_period_raw raw
            JOIN final_audience fa
              ON raw.movie_name_clean = fa.movie_name_clean
             AND raw.release_date = fa.release_date
        )
        SELECT
            id AS raw_id,
            source_file,
            period_start,
            period_end,
            rank,
            movie_name,
            movie_name_clean,
            release_date,
            sales_amount,
            sales_share,
            cumulative_sales_amount,
            audience_count,
            cumulative_audience,
            target_final_audience,
            screen_count,
            show_count,
            primary_country,
            country,
            production_company,
            distributor,
            rating,
            genre,
            director,
            actors
        FROM ranked
        WHERE snapshot_rank = 1;

        CREATE UNIQUE INDEX idx_snapshot_movie_release
            ON movie_snapshot (movie_name_clean, release_date);
        """
    )


def build_snapshot_selected(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE movie_snapshot_selected AS
        SELECT
            movie_name_clean,
            release_date,
            cumulative_sales_amount,
            cumulative_audience,
            country,
            production_company,
            distributor,
            rating,
            genre,
            director,
            actors AS actor
        FROM movie_snapshot;

        CREATE UNIQUE INDEX idx_snapshot_selected_movie_release
            ON movie_snapshot_selected (movie_name_clean, release_date);
        """
    )


if __name__ == "__main__":
    main()
