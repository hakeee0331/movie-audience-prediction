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

from utils.kmdb_api import KmdbApiClient, choose_kmdb_match, parse_kmdb_detail, utc_now


MISSING_CONDITION = """
    production_company IS NULL OR TRIM(production_company) = ''
    OR actor IS NULL OR TRIM(actor) = ''
    OR director IS NULL OR TRIM(director) = ''
    OR distributor IS NULL OR TRIM(distributor) = ''
    OR rating IS NULL OR TRIM(rating) = ''
    OR genre IS NULL OR TRIM(genre) = ''
    OR country IS NULL OR TRIM(country) = ''
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich movie metadata with KMDb API.")
    parser.add_argument("--db-path", type=Path, default=ROOT / "data" / "db" / "kobis_movies.db")
    parser.add_argument("--api-key", default=os.environ.get("KMDB_API_KEY") or read_dotenv_api_key("KMDB_API_KEY"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--refresh", action="store_true", help="Fetch matches again even if cached.")
    parser.add_argument("--rebuild-only", action="store_true", help="Rebuild enriched table from cached KMDb data.")
    parser.add_argument("--export-csv", action="store_true", help="Export movie_snapshot_enriched CSV files.")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("KMDb API key is required. Set KMDB_API_KEY or pass --api-key.")

    client = KmdbApiClient(api_key=args.api_key, sleep_seconds=args.sleep_seconds)
    with sqlite3.connect(args.db_path) as conn:
        conn.row_factory = sqlite3.Row
        create_kmdb_tables(conn)
        ensure_enriched_exists(conn)
        before = missing_counts(conn, "movie_snapshot_enriched")

        if args.rebuild_only:
            reparse_matched_details(conn)
            build_enriched_table(conn)
            after = missing_counts(conn, "movie_snapshot_enriched")
            print_missing_report(before, after)
            if args.export_csv:
                export_enriched_csv(conn)
            return

        rows = rows_to_enrich(conn, limit=args.limit, refresh=args.refresh)
        print(f"Rows to search: {len(rows):,}")
        for index, row in enumerate(rows, start=1):
            enrich_kmdb_match(conn, client, row)
            if index % 25 == 0:
                conn.commit()
                print(f"KMDb search progress: {index:,}/{len(rows):,}")
        conn.commit()

        reparse_matched_details(conn)
        build_enriched_table(conn)
        after = missing_counts(conn, "movie_snapshot_enriched")
        print_missing_report(before, after)

        if args.export_csv:
            export_enriched_csv(conn)


def create_kmdb_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kmdb_movie_match (
            movie_name_clean TEXT NOT NULL,
            release_date TEXT NOT NULL,
            kmdb_movie_id TEXT,
            kmdb_movie_seq TEXT,
            kmdb_doc_id TEXT,
            kmdb_title TEXT,
            kmdb_release_date TEXT,
            match_status TEXT NOT NULL,
            match_rule TEXT,
            match_score REAL NOT NULL,
            candidate_count INTEGER NOT NULL,
            raw_response_json TEXT,
            matched_record_json TEXT,
            fetched_at TEXT NOT NULL,
            error_message TEXT,
            PRIMARY KEY (movie_name_clean, release_date)
        );

        CREATE TABLE IF NOT EXISTS kmdb_movie_detail (
            kmdb_movie_id TEXT,
            kmdb_movie_seq TEXT,
            kmdb_doc_id TEXT,
            title TEXT,
            title_en TEXT,
            release_date TEXT,
            countries TEXT,
            genres TEXT,
            directors TEXT,
            actors TEXT,
            production_companies TEXT,
            distributors TEXT,
            ratings TEXT,
            poster_url TEXT,
            synopsis TEXT,
            raw_record_json TEXT,
            fetched_at TEXT NOT NULL,
            error_message TEXT,
            PRIMARY KEY (kmdb_movie_id, kmdb_movie_seq, kmdb_doc_id)
        );
        """
    )
    ensure_column(conn, "kmdb_movie_detail", "poster_url", "TEXT")
    ensure_column(conn, "kmdb_movie_detail", "synopsis", "TEXT")


def ensure_enriched_exists(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'movie_snapshot_enriched'"
    ).fetchone()[0]
    if not exists:
        conn.execute(
            """
            CREATE TABLE movie_snapshot_enriched AS
            SELECT
                *,
                NULL AS kobis_movie_cd,
                NULL AS kobis_match_status,
                NULL AS kobis_match_rule,
                NULL AS kobis_match_score
            FROM movie_snapshot_selected
            """
        )


def rows_to_enrich(conn: sqlite3.Connection, limit: int | None, refresh: bool) -> list[sqlite3.Row]:
    where = f"WHERE ({MISSING_CONDITION})"
    if not refresh:
        where += """
            AND NOT EXISTS (
                SELECT 1
                FROM kmdb_movie_match m
                WHERE m.movie_name_clean = e.movie_name_clean
                  AND m.release_date = e.release_date
            )
        """
    limit_sql = f"LIMIT {limit}" if limit else ""
    return list(
        conn.execute(
            f"""
            SELECT movie_name_clean, release_date
            FROM movie_snapshot_enriched e
            {where}
            ORDER BY
                CASE
                    WHEN director IS NULL OR TRIM(director) = '' THEN 0
                    WHEN actor IS NULL OR TRIM(actor) = '' THEN 1
                    WHEN production_company IS NULL OR TRIM(production_company) = '' THEN 2
                    ELSE 3
                END,
                release_date DESC,
                movie_name_clean ASC
            {limit_sql}
            """
        )
    )


def enrich_kmdb_match(conn: sqlite3.Connection, client: KmdbApiClient, row: sqlite3.Row) -> None:
    movie_name = row["movie_name_clean"]
    release_date = row["release_date"]
    fetched_at = utc_now()
    try:
        response = client.search_movies(movie_name)
        match = choose_kmdb_match(movie_name, release_date, response)
    except Exception as exc:
        conn.execute(
            """
            INSERT OR REPLACE INTO kmdb_movie_match (
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
        INSERT OR REPLACE INTO kmdb_movie_match (
            movie_name_clean, release_date, kmdb_movie_id, kmdb_movie_seq, kmdb_doc_id,
            kmdb_title, kmdb_release_date, match_status, match_rule, match_score,
            candidate_count, raw_response_json, matched_record_json, fetched_at, error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            movie_name,
            release_date,
            match.kmdb_movie_id,
            match.kmdb_movie_seq,
            match.kmdb_doc_id,
            match.title,
            match.release_date,
            match.status,
            match.rule,
            match.score,
            match.candidate_count,
            match.raw_response_json,
            match.matched_record_json,
            fetched_at,
            match.error_message,
        ),
    )

    if match.status == "matched":
        detail = parse_kmdb_detail(match.matched_record_json)
        conn.execute(
            """
            INSERT OR REPLACE INTO kmdb_movie_detail (
                kmdb_movie_id, kmdb_movie_seq, kmdb_doc_id, title, title_en, release_date,
                countries, genres, directors, actors, production_companies, distributors,
                ratings, poster_url, synopsis, raw_record_json, fetched_at, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                detail["kmdb_movie_id"],
                detail["kmdb_movie_seq"],
                detail["kmdb_doc_id"],
                detail["title"],
                detail["title_en"],
                detail["release_date"],
                detail["countries"],
                detail["genres"],
                detail["directors"],
                detail["actors"],
                detail["production_companies"],
                detail["distributors"],
                detail["ratings"],
                detail["poster_url"],
                detail["synopsis"],
                detail["raw_record_json"],
                detail["fetched_at"],
                None,
            ),
        )


def reparse_matched_details(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT matched_record_json
        FROM kmdb_movie_match
        WHERE match_status = 'matched'
          AND matched_record_json IS NOT NULL
        """
    )
    for row in rows:
        detail = parse_kmdb_detail(row["matched_record_json"])
        conn.execute(
            """
            INSERT OR REPLACE INTO kmdb_movie_detail (
                kmdb_movie_id, kmdb_movie_seq, kmdb_doc_id, title, title_en, release_date,
                countries, genres, directors, actors, production_companies, distributors,
                ratings, poster_url, synopsis, raw_record_json, fetched_at, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                detail["kmdb_movie_id"],
                detail["kmdb_movie_seq"],
                detail["kmdb_doc_id"],
                detail["title"],
                detail["title_en"],
                detail["release_date"],
                detail["countries"],
                detail["genres"],
                detail["directors"],
                detail["actors"],
                detail["production_companies"],
                detail["distributors"],
                detail["ratings"],
                detail["poster_url"],
                detail["synopsis"],
                detail["raw_record_json"],
                detail["fetched_at"],
                None,
            ),
        )
    conn.commit()


def build_enriched_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS movie_snapshot_enriched_new;

        CREATE TABLE movie_snapshot_enriched_new AS
        SELECT
            s.movie_name_clean,
            s.release_date,
            s.cumulative_sales_amount,
            s.cumulative_audience,
            COALESCE(NULLIF(TRIM(s.country), ''), kd.countries, md.countries) AS country,
            COALESCE(NULLIF(TRIM(s.production_company), ''), kd.production_companies, md.production_companies) AS production_company,
            COALESCE(NULLIF(TRIM(s.distributor), ''), kd.distributors, md.distributors) AS distributor,
            COALESCE(NULLIF(TRIM(s.rating), ''), kd.ratings, md.ratings) AS rating,
            COALESCE(NULLIF(TRIM(s.genre), ''), kd.genres, md.genres) AS genre,
            COALESCE(NULLIF(TRIM(s.director), ''), kd.directors, md.directors) AS director,
            COALESCE(NULLIF(TRIM(s.actor), ''), kd.actors, md.actors) AS actor,
            km.kobis_movie_cd,
            km.match_status AS kobis_match_status,
            km.match_rule AS kobis_match_rule,
            km.match_score AS kobis_match_score,
            mm.kmdb_movie_id,
            mm.kmdb_movie_seq,
            mm.kmdb_doc_id,
            mm.match_status AS kmdb_match_status,
            mm.match_rule AS kmdb_match_rule,
            mm.match_score AS kmdb_match_score,
            md.poster_url,
            md.synopsis
        FROM movie_snapshot_selected s
        LEFT JOIN kobis_movie_match km
          ON s.movie_name_clean = km.movie_name_clean
         AND s.release_date = km.release_date
         AND km.match_status = 'matched'
        LEFT JOIN kobis_movie_detail kd
          ON km.kobis_movie_cd = kd.kobis_movie_cd
        LEFT JOIN kmdb_movie_match mm
          ON s.movie_name_clean = mm.movie_name_clean
         AND s.release_date = mm.release_date
         AND mm.match_status = 'matched'
        LEFT JOIN kmdb_movie_detail md
          ON mm.kmdb_movie_id = md.kmdb_movie_id
         AND mm.kmdb_movie_seq = md.kmdb_movie_seq
         AND mm.kmdb_doc_id = md.kmdb_doc_id;

        DROP TABLE IF EXISTS movie_snapshot_enriched;
        ALTER TABLE movie_snapshot_enriched_new RENAME TO movie_snapshot_enriched;

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


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


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


def read_dotenv_api_key(key_name: str) -> str | None:
    dotenv_path = ROOT / ".env"
    if not dotenv_path.exists():
        return None
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == key_name:
            return value.strip().strip('"').strip("'")
    return None


if __name__ == "__main__":
    main()
