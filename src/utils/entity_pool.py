"""Shared helpers for popular entity pool generation and feature extraction."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path


EMPTY_VALUES = {"", "-", "--", "nan", "none", "null", "정보없음", "N/A", "n/a"}
NORMALIZED_ENTITY_TYPES = {"production_company", "distributor"}


def clean_entity_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_entity_key(value: str) -> str:
    text = value.lower().replace("㈜", "주")
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def split_entities(value: object) -> list[str]:
    if value is None:
        return []

    text = str(value).strip()
    if text in EMPTY_VALUES:
        return []

    entities = []
    for part in text.replace("|", ",").replace(";", ",").split(","):
        name = clean_entity_name(part)
        if name and name not in EMPTY_VALUES:
            entities.append(name)

    return sorted(set(entities))


def load_alias_rules(path: Path) -> dict[str, list[dict[str, object]]]:
    if not path.exists():
        return {}

    rules: dict[str, list[dict[str, object]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entity_type = clean_entity_name(row["entity_type"])
            canonical_entity = clean_entity_name(row["canonical_entity"])
            aliases = [
                normalize_entity_key(alias)
                for alias in row["aliases"].split("|")
                if normalize_entity_key(alias)
            ]
            aliases = sorted(set(aliases), key=len, reverse=True)
            rules[entity_type].append(
                {
                    "canonical_entity": canonical_entity,
                    "entity_key": f"canonical:{normalize_entity_key(canonical_entity)}",
                    "aliases": aliases,
                }
            )

    for entity_type in rules:
        rules[entity_type].sort(
            key=lambda rule: max((len(alias) for alias in rule["aliases"]), default=0),
            reverse=True,
        )

    return rules


def resolve_entity_identity(
    entity: str,
    entity_type: str,
    alias_rules: dict[str, list[dict[str, object]]],
) -> tuple[str, str]:
    normalized_entity = normalize_entity_key(entity)
    if entity_type in NORMALIZED_ENTITY_TYPES:
        for rule in alias_rules.get(entity_type, []):
            if any(alias in normalized_entity for alias in rule["aliases"]):
                return rule["entity_key"], rule["canonical_entity"]

        return normalized_entity, entity

    return entity, entity
