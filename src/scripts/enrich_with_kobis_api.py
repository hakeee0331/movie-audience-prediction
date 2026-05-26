from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.kobis_api import KobisApiClient, choose_movie_match, parse_movie_detail, utc_now


MISSING_CONDITION = """
    country IS NULL OR TRIM(country) = ''
    OR production_company IS NULL OR TRIM(production_company) = ''
    OR distributor IS NULL OR TRIM(distributor) = ''
    OR rating IS NULL OR TRIM(rating) = ''
    OR genre IS NULL OR TRIM(genre) = ''
    OR director IS NULL OR TRIM(director) = ''
    OR actor IS NULL OR TRIM(actor) = ''
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich movie metadata with KOBIS Open API.")
    parser.add_argument("--db-path", type=Path, default=ROOT / "data" / "db" / "kobis_movies.db")
    parser.add_argument("--api-key", default=os.environ.get("KOBIS_API_KEY") or read_dotenv_api_key())
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--refresh", action="store_true", help="Fetch matches/details again even if cached.")
    parser.add_argument("--export-csv", action="store_true", help="Export movie_snapshot_enriched CSV files.")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("KOBIS API key is required. Set KOBIS_API_KEY or pass --api-key.")

    client = KobisApiClient(api_key=args.api_key, sleep_seconds=args.sleep_seconds)

    with sqlite3.connect(args.db_path) as conn:
        conn.row_factory = sqlite3.Row
        create_enrichment_tables(conn)
        before = missing_counts(conn, "movie_snapshot_selected")
        rows = rows_to_enrich(conn, limit=args.limit, refresh=args.refresh)
        print(f"Rows to search: {len(rows):,}")

        for index, row in enumerate(rows, start=1):
            enrich_match(conn, client, row)
            if index % 50 == 0:
                conn.commit()
                print(f"Matched search progress: {index:,}/{len(rows):,}")
        conn.commit()

        detail_rows = matched_rows_missing_detail(conn, refresh=args.refresh)
        print(f"Movie details to fetch: {len(detail_rows):,}")
        for index, row in enumerate(detail_rows, start=1):
            enrich_detail(conn, client, row["kobis_movie_cd"])
            if index % 50 == 0:
                conn.commit()
                print(f"Detail fetch progress: {index:,}/{len(detail_rows):,}")
        conn.commit()

        build_enriched_table(conn)
        after = missing_counts(conn, "movie_snapshot_enriched")
        print_missing_report(before, after)

        if args.export_csv:
            export_enriched_csv(conn)


def create_enrichment_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kobis_movie_match (
            movie_name_clean TEXT NOT NULL,
            release_date TEXT NOT NULL,
            kobis_movie_cd TEXT,
            kobis_movie_nm TEXT,
            kobis_open_dt TEXT,
            match_status TEXT NOT NULL,
            match_rule TEXT,
            match_score REAL NOT NULL,
            candidate_count INTEGER NOT NULL,
            raw_response_json TEXT,
            fetched_at TEXT NOT NULL,
            error_message TEXT,
            PRIMARY KEY (movie_name_clean, release_date)
        );

        CREATE TABLE IF NOT EXISTS kobis_movie_detail (
            kobis_movie_cd TEXT PRIMARY KEY,
            movie_name TEXT,
            movie_name_en TEXT,
            open_date TEXT,
            countries TEXT,
            genres TEXT,
            directors TEXT,
            actors TEXT,
            production_companies TEXT,
            distributors TEXT,
            ratings TEXT,
            raw_response_json TEXT,
            fetched_at TEXT NOT NULL,
            error_message TEXT
        );
        """
    )


def rows_to_enrich(conn: sqlite3.Connection, limit: int | None, refresh: bool) -> list[sqlite3.Row]:
    where = f"WHERE ({MISSING_CONDITION})"
    if not refresh:
        where += """
            AND NOT EXISTS (
                SELECT 1
                FROM kobis_movie_match m
                WHERE m.movie_name_clean = s.movie_name_clean
                  AND m.release_date = s.release_date
            )
        """
    limit_sql = f"LIMIT {limit}" if limit else ""
    return list(
        conn.execute(
            f"""
            SELECT movie_name_clean, release_date
            FROM movie_snapshot_selected s
            {where}
            ORDER BY release_date DESC, movie_name_clean ASC
            {limit_sql}
            """
        )
    )


def enrich_match(conn: sqlite3.Connection, client: KobisApiClient, row: sqlite3.Row) -> None:
    movie_name = row["movie_name_clean"]
    release_date = row["release_date"]
    fetched_at = utc_now()
    try:
        response = client.search_movie_list(movie_name, release_date)
        match = choose_movie_match(movie_name, release_date, response)
    except Exception as exc:
        conn.execute(
            """
            INSERT OR REPLACE INTO kobis_movie_match (
                movie_name_clean, release_date, match_status, match_rule, match_score,
                candidate_count, fetched_at, error_message
            )
            VALUES (?, ?, 'error', NULL, 0, 0, ?, ?)
            """,
            (movie_name, release_date, fetched_at, str(exc)),
        )
        return

    conn.execute(
        """
        INSERT OR REPLACE INTO kobis_movie_match (
            movie_name_clean, release_date, kobis_movie_cd, kobis_movie_nm, kobis_open_dt,
            match_status, match_rule, match_score, candidate_count, raw_response_json,
            fetched_at, error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            movie_name,
            release_date,
            match.movie_cd,
            match.movie_nm,
            match.open_dt,
            match.status,
            match.rule,
            match.score,
            match.candidate_count,
            match.raw_response_json,
            fetched_at,
            match.error_message,
        ),
    )


def matched_rows_missing_detail(conn: sqlite3.Connection, refresh: bool) -> list[sqlite3.Row]:
    where = "WHERE match_status = 'matched' AND kobis_movie_cd IS NOT NULL"
    if not refresh:
        where += """
            AND NOT EXISTS (
                SELECT 1
                FROM kobis_movie_detail d
                WHERE d.kobis_movie_cd = m.kobis_movie_cd
            )
        """
    return list(
        conn.execute(
            f"""
            SELECT DISTINCT kobis_movie_cd
            FROM kobis_movie_match m
            {where}
            ORDER BY kobis_movie_cd
            """
        )
    )


def enrich_detail(conn: sqlite3.Connection, client: KobisApiClient, movie_cd: str) -> None:
    try:
        response = client.search_movie_info(movie_cd)
        detail = parse_movie_detail(response)
        detail["error_message"] = None
    except Exception as exc:
        detail = {
            "kobis_movie_cd": movie_cd,
            "movie_name": None,
            "movie_name_en": None,
            "open_date": None,
            "countries": None,
            "genres": None,
            "directors": None,
            "actors": None,
            "production_companies": None,
            "distributors": None,
            "ratings": None,
            "raw_response_json": None,
            "fetched_at": utc_now(),
            "error_message": str(exc),
        }

    conn.execute(
        """
        INSERT OR REPLACE INTO kobis_movie_detail (
            kobis_movie_cd, movie_name, movie_name_en, open_date, countries, genres,
            directors, actors, production_companies, distributors, ratings,
            raw_response_json, fetched_at, error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            detail["kobis_movie_cd"],
            detail["movie_name"],
            detail["movie_name_en"],
            detail["open_date"],
            detail["countries"],
            detail["genres"],
            detail["directors"],
            detail["actors"],
            detail["production_companies"],
            detail["distributors"],
            detail["ratings"],
            detail["raw_response_json"],
            detail["fetched_at"],
            detail["error_message"],
        ),
    )


def build_enriched_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS movie_snapshot_enriched;

        CREATE TABLE movie_snapshot_enriched AS
        SELECT
            s.movie_name_clean,
            s.release_date,
            s.cumulative_sales_amount,
            s.cumulative_audience,
            s.show_count,
            COALESCE(NULLIF(TRIM(s.country), ''), d.countries) AS country,
            COALESCE(NULLIF(TRIM(s.production_company), ''), d.production_companies) AS production_company,
            COALESCE(NULLIF(TRIM(s.distributor), ''), d.distributors) AS distributor,
            COALESCE(NULLIF(TRIM(s.rating), ''), d.ratings) AS rating,
            COALESCE(NULLIF(TRIM(s.genre), ''), d.genres) AS genre,
            COALESCE(NULLIF(TRIM(s.director), ''), d.directors) AS director,
            COALESCE(NULLIF(TRIM(s.actor), ''), d.actors) AS actor,
            m.kobis_movie_cd,
            m.match_status AS kobis_match_status,
            m.match_rule AS kobis_match_rule,
            m.match_score AS kobis_match_score
        FROM movie_snapshot_selected s
        LEFT JOIN kobis_movie_match m
          ON s.movie_name_clean = m.movie_name_clean
         AND s.release_date = m.release_date
         AND m.match_status = 'matched'
        LEFT JOIN kobis_movie_detail d
          ON m.kobis_movie_cd = d.kobis_movie_cd;

        CREATE UNIQUE INDEX idx_snapshot_enriched_movie_release
            ON movie_snapshot_enriched (movie_name_clean, release_date);
        """
    )


def missing_counts(conn: sqlite3.Connection, table_name: str) -> dict[str, int]:
    columns = ["country", "production_company", "distributor", "rating", "genre", "director", "actor"]
    counts = {}
    for column in columns:
        counts[column] = conn.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE {column} IS NULL OR TRIM({column}) = ''"
        ).fetchone()[0]
    return counts


def print_missing_report(before: dict[str, int], after: dict[str, int]) -> None:
    print("Missing value report")
    for column in before:
        delta = before[column] - after[column]
        print(f"- {column}: {before[column]:,} -> {after[column]:,} ({delta:,} filled)")


def export_enriched_csv(conn: sqlite3.Connection) -> None:
    output_dir = ROOT / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "movie_snapshot_enriched.csv"
    utf8_sig_path = output_dir / "movie_snapshot_enriched_utf8_sig.csv"
    rows = conn.execute("SELECT * FROM movie_snapshot_enriched ORDER BY release_date, movie_name_clean")
    columns = [description[0] for description in rows.description]

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)

    utf8_sig_path.write_bytes(b"\xef\xbb\xbf" + csv_path.read_bytes())
    print(f"Exported {csv_path}")
    print(f"Exported {utf8_sig_path}")


def read_dotenv_api_key() -> str | None:
    dotenv_path = ROOT / ".env"
    if not dotenv_path.exists():
        return None

    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "KOBIS_API_KEY":
            return value.strip().strip('"').strip("'")
    return None


if __name__ == "__main__":
    main()
