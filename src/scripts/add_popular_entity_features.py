#!/usr/bin/env python3
"""Create movie-level popular entity features from prebuilt entity pools."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.entity_pool import load_alias_rules
from src.utils.entity_pool import resolve_entity_identity
from src.utils.entity_pool import split_entities


DEFAULT_INPUT_CSV = PROJECT_ROOT / "data/processed/movie_snapshot_enriched_utf8_sig.csv"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "data/processed/popular_entity_features_utf8_sig.csv"
DEFAULT_POOL_DIR = PROJECT_ROOT / "data/processed/entity_pools"
DEFAULT_ALIAS_MAP_PATH = PROJECT_ROOT / "docs/company_alias_map_utf8_sig.csv"

POOL_FILES = {
    "director": "popular_director_pool_utf8_sig.csv",
    "actor": "popular_actor_pool_utf8_sig.csv",
    "production_company": "popular_production_company_pool_utf8_sig.csv",
    "distributor": "popular_distributor_pool_utf8_sig.csv",
}

OUTPUT_FIELDNAMES = [
    "movie_name_clean",
    "release_date",
    "has_popular_director",
    "popular_director_count",
    "has_popular_actor",
    "popular_actor_count",
    "top_popular_actor_mean_audience",
    "has_popular_production_company",
    "popular_production_company_count",
    "has_popular_distributor",
    "popular_distributor_count",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add popular entity features from prebuilt entity pools.",
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--pool-dir", type=Path, default=DEFAULT_POOL_DIR)
    parser.add_argument("--alias-map-path", type=Path, default=DEFAULT_ALIAS_MAP_PATH)
    return parser.parse_args()


def load_pool(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {row["entity_key"]: row for row in csv.DictReader(f)}


def to_float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def entity_keys_for_row(
    row: dict[str, str],
    entity_type: str,
    alias_rules: dict[str, list[dict[str, object]]],
) -> list[str]:
    keys = []
    for entity in split_entities(row.get(entity_type, "")):
        entity_key, _ = resolve_entity_identity(
            entity=entity,
            entity_type=entity_type,
            alias_rules=alias_rules,
        )
        if entity_key:
            keys.append(entity_key)

    return sorted(set(keys))


def count_pool_hits(entity_keys: list[str], pool: dict[str, dict[str, str]]) -> int:
    return sum(1 for key in entity_keys if key in pool)


def max_actor_mean_audience(actor_keys: list[str], actor_pool: dict[str, dict[str, str]]) -> float:
    scores = [
        to_float(actor_pool[key].get("mean_audience"))
        for key in actor_keys
        if key in actor_pool
    ]
    return max(scores, default=0.0)


def build_feature_row(
    row: dict[str, str],
    pools: dict[str, dict[str, dict[str, str]]],
    alias_rules: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    director_keys = entity_keys_for_row(row, "director", alias_rules)
    actor_keys = entity_keys_for_row(row, "actor", alias_rules)
    production_company_keys = entity_keys_for_row(row, "production_company", alias_rules)
    distributor_keys = entity_keys_for_row(row, "distributor", alias_rules)

    popular_director_count = count_pool_hits(director_keys, pools["director"])
    popular_actor_count = count_pool_hits(actor_keys, pools["actor"])
    popular_production_company_count = count_pool_hits(
        production_company_keys,
        pools["production_company"],
    )
    popular_distributor_count = count_pool_hits(distributor_keys, pools["distributor"])

    return {
        "movie_name_clean": row["movie_name_clean"],
        "release_date": row["release_date"],
        "has_popular_director": int(popular_director_count > 0),
        "popular_director_count": popular_director_count,
        "has_popular_actor": int(popular_actor_count > 0),
        "popular_actor_count": popular_actor_count,
        "top_popular_actor_mean_audience": round(
            max_actor_mean_audience(actor_keys, pools["actor"]),
            2,
        ),
        "has_popular_production_company": int(popular_production_company_count > 0),
        "popular_production_company_count": popular_production_company_count,
        "has_popular_distributor": int(popular_distributor_count > 0),
        "popular_distributor_count": popular_distributor_count,
    }


def validate_output(rows: list[dict[str, object]]) -> None:
    keys = [(row["movie_name_clean"], row["release_date"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate movie_name_clean + release_date rows found in output")

    has_columns = [
        "has_popular_director",
        "has_popular_actor",
        "has_popular_production_company",
        "has_popular_distributor",
    ]
    count_columns = [
        "popular_director_count",
        "popular_actor_count",
        "popular_production_company_count",
        "popular_distributor_count",
    ]

    for row in rows:
        for column in has_columns:
            if row[column] not in (0, 1):
                raise ValueError(f"{column} must be 0 or 1")
        for column in count_columns:
            if row[column] < 0:
                raise ValueError(f"{column} must be non-negative")


def main() -> None:
    args = parse_args()
    pools = {
        entity_type: load_pool(args.pool_dir / file_name)
        for entity_type, file_name in POOL_FILES.items()
    }
    alias_rules = load_alias_rules(args.alias_map_path)

    with args.input_csv.open(encoding="utf-8-sig", newline="") as f:
        input_rows = list(csv.DictReader(f))

    output_rows = [
        build_feature_row(row=row, pools=pools, alias_rules=alias_rules)
        for row in input_rows
    ]
    validate_output(output_rows)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote {len(output_rows):,} rows to {args.output_csv}")


if __name__ == "__main__":
    main()
