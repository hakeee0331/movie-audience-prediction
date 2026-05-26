from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate KOBIS SQLite DB.")
    parser.add_argument("--db-path", type=Path, default=ROOT / "data" / "db" / "kobis_movies.db")
    args = parser.parse_args()

    if not args.db_path.exists():
        raise SystemExit(f"DB file does not exist: {args.db_path}")

    with sqlite3.connect(args.db_path) as conn:
        required_tables = {"boxoffice_period_raw", "movie_snapshot", "movie_snapshot_selected"}
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        missing = required_tables - tables
        if missing:
            raise SystemExit(f"Missing tables: {sorted(missing)}")

        checks = [
            ("raw rows > 0", scalar(conn, "SELECT COUNT(*) FROM boxoffice_period_raw") > 0),
            ("snapshot rows > 0", scalar(conn, "SELECT COUNT(*) FROM movie_snapshot") > 0),
            (
                "selected snapshot rows match snapshot rows",
                scalar(conn, "SELECT COUNT(*) FROM movie_snapshot_selected")
                == scalar(conn, "SELECT COUNT(*) FROM movie_snapshot"),
            ),
            (
                "selected snapshot columns are expected",
                table_columns(conn, "movie_snapshot_selected")
                == [
                    "movie_name_clean",
                    "release_date",
                    "cumulative_sales_amount",
                    "cumulative_audience",
                    "show_count",
                    "country",
                    "production_company",
                    "distributor",
                    "rating",
                    "genre",
                    "director",
                    "actor",
                ],
            ),
            (
                "no duplicate movie snapshots",
                scalar(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT movie_name_clean, release_date
                        FROM movie_snapshot
                        GROUP BY movie_name_clean, release_date
                        HAVING COUNT(*) > 1
                    )
                    """,
                )
                == 0,
            ),
            (
                "target_final_audience is present and non-negative",
                scalar(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM movie_snapshot
                    WHERE target_final_audience IS NULL
                       OR target_final_audience < 0
                    """,
                )
                == 0,
            ),
            (
                "show_count is present and non-negative",
                scalar(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM movie_snapshot
                    WHERE show_count IS NULL
                       OR show_count < 0
                    """,
                )
                == 0,
            ),
            (
                "period_start <= period_end",
                scalar(
                    conn,
                    """
                    SELECT COUNT(*)
                    FROM boxoffice_period_raw
                    WHERE period_start IS NOT NULL
                      AND period_end IS NOT NULL
                      AND period_start > period_end
                    """,
                )
                == 0,
            ),
        ]

    failed = [name for name, ok in checks if not ok]
    if failed:
        raise SystemExit("Validation failed: " + ", ".join(failed))

    print("Validation passed")
    print(f"Raw rows: {scalar_from_path(args.db_path, 'SELECT COUNT(*) FROM boxoffice_period_raw'):,}")
    print(f"Snapshot rows: {scalar_from_path(args.db_path, 'SELECT COUNT(*) FROM movie_snapshot'):,}")
    print(
        "Selected snapshot rows: "
        f"{scalar_from_path(args.db_path, 'SELECT COUNT(*) FROM movie_snapshot_selected'):,}"
    )


def scalar(conn: sqlite3.Connection, query: str):
    return conn.execute(query).fetchone()[0]


def scalar_from_path(db_path: Path, query: str):
    with sqlite3.connect(db_path) as conn:
        return scalar(conn, query)


def table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]


if __name__ == "__main__":
    main()
