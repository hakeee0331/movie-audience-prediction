#!/usr/bin/env python3
"""Build popular director/company/distributor/actor pools from enriched data."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.entity_pool import load_alias_rules
from src.utils.entity_pool import resolve_entity_identity
from src.utils.entity_pool import split_entities


DEFAULT_DB_PATH = PROJECT_ROOT / "data/db/kobis_movies.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data/processed/entity_pools"
DEFAULT_ALIAS_MAP_PATH = PROJECT_ROOT / "docs/company_alias_map_utf8_sig.csv"

ENTITY_CONFIGS = {
    "director": {
        "column": "director",
        "min_movie_count": 2,
        "top_n": 100,
    },
    "actor": {
        "column": "actor",
        "min_movie_count": 3,
        "top_n": 300,
    },
    "production_company": {
        "column": "production_company",
        "min_movie_count": 2,
        "top_n": 100,
    },
    "distributor": {
        "column": "distributor",
        "min_movie_count": 2,
        "top_n": 50,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build popular entity pools using target_final_audience.",
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--alias-map-path", type=Path, default=DEFAULT_ALIAS_MAP_PATH)
    return parser.parse_args()


def fetch_rows(db_path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT
                e.movie_name_clean,
                e.release_date,
                e.director,
                e.actor,
                e.production_company,
                e.distributor,
                COALESCE(s.target_final_audience, e.cumulative_audience) AS audience
            FROM movie_snapshot_enriched AS e
            LEFT JOIN movie_snapshot AS s
                ON e.movie_name_clean = s.movie_name_clean
               AND e.release_date = s.release_date
            """
        ).fetchall()
    finally:
        conn.close()


def audience_to_int(value: object) -> int:
    if value is None or value == "":
        return 0
    return int(float(value))


def build_pool(
    rows: list[sqlite3.Row],
    entity_type: str,
    column: str,
    min_movie_count: int,
    top_n: int,
    alias_rules: Optional[dict[str, list[dict[str, object]]]] = None,
) -> list[dict[str, object]]:
    alias_rules = alias_rules or {}
    stats: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "movie_keys": set(),
            "audiences": [],
            "raw_entity_counts": Counter(),
            "canonical_entity": "",
            "hit_1m_count": 0,
            "hit_3m_count": 0,
            "hit_5m_count": 0,
        }
    )

    for row in rows:
        audience = audience_to_int(row["audience"])
        movie_key = (row["movie_name_clean"], row["release_date"])
        for entity in split_entities(row[column]):
            entity_key, display_entity = resolve_entity_identity(
                entity=entity,
                entity_type=entity_type,
                alias_rules=alias_rules,
            )
            if not entity_key:
                continue

            entity_stats = stats[entity_key]
            if display_entity != entity:
                entity_stats["canonical_entity"] = display_entity
            if movie_key in entity_stats["movie_keys"]:
                continue

            entity_stats["movie_keys"].add(movie_key)
            entity_stats["audiences"].append(audience)
            entity_stats["raw_entity_counts"][entity] += 1
            if audience >= 1_000_000:
                entity_stats["hit_1m_count"] += 1
            if audience >= 3_000_000:
                entity_stats["hit_3m_count"] += 1
            if audience >= 5_000_000:
                entity_stats["hit_5m_count"] += 1

    pool_rows = []
    for entity_key, entity_stats in stats.items():
        audiences = entity_stats["audiences"]
        movie_count = len(audiences)
        if movie_count < min_movie_count:
            continue

        total_audience = sum(audiences)
        raw_entity_counts = entity_stats["raw_entity_counts"]
        representative_entity = entity_stats["canonical_entity"] or raw_entity_counts.most_common(1)[0][0]
        pool_rows.append(
            {
                "entity": representative_entity,
                "entity_key": entity_key,
                "raw_entity_variants": "|".join(sorted(raw_entity_counts)),
                "movie_count": movie_count,
                "total_audience": total_audience,
                "mean_audience": round(total_audience / movie_count, 2),
                "median_audience": int(median(audiences)),
                "max_audience": max(audiences),
                "hit_1m_count": entity_stats["hit_1m_count"],
                "hit_3m_count": entity_stats["hit_3m_count"],
                "hit_5m_count": entity_stats["hit_5m_count"],
            }
        )

    pool_rows.sort(
        key=lambda row: (
            row["total_audience"],
            row["hit_5m_count"],
            row["hit_3m_count"],
            row["movie_count"],
            row["mean_audience"],
        ),
        reverse=True,
    )
    return pool_rows[:top_n]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "rank",
        "entity",
        "entity_key",
        "raw_entity_variants",
        "movie_count",
        "total_audience",
        "mean_audience",
        "median_audience",
        "max_audience",
        "hit_1m_count",
        "hit_3m_count",
        "hit_5m_count",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rank, row in enumerate(rows, start=1):
            writer.writerow({"rank": rank, **row})


def main() -> None:
    args = parse_args()
    rows = fetch_rows(args.db_path)
    alias_rules = load_alias_rules(args.alias_map_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for entity_type, config in ENTITY_CONFIGS.items():
        pool_rows = build_pool(
            rows=rows,
            entity_type=entity_type,
            column=config["column"],
            min_movie_count=config["min_movie_count"],
            top_n=config["top_n"],
            alias_rules=alias_rules,
        )
        output_path = args.output_dir / f"popular_{entity_type}_pool_utf8_sig.csv"
        write_csv(output_path, pool_rows)
        print(
            f"{entity_type}: wrote {len(pool_rows):,} rows "
            f"(min_movie_count={config['min_movie_count']}, top_n={config['top_n']}) "
            f"to {output_path}"
        )


if __name__ == "__main__":
    main()
