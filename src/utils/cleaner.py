from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional


COLUMN_MAP = {
    "순위": "rank",
    "영화명": "movie_name",
    "개봉일": "release_date",
    "매출액": "sales_amount",
    "매출액점유율": "sales_share",
    "누적매출액": "cumulative_sales_amount",
    "관객수": "audience_count",
    "누적관객수": "cumulative_audience",
    "스크린수": "screen_count",
    "상영횟수": "show_count",
    "대표국적": "primary_country",
    "국적": "country",
    "제작사": "production_company",
    "배급사": "distributor",
    "등급": "rating",
    "장르": "genre",
    "감독": "director",
    "배우": "actors",
}

INTEGER_COLUMNS = {
    "rank",
    "sales_amount",
    "cumulative_sales_amount",
    "audience_count",
    "cumulative_audience",
    "screen_count",
    "show_count",
}

TEXT_COLUMNS = {
    "movie_name",
    "primary_country",
    "country",
    "production_company",
    "distributor",
    "rating",
    "genre",
    "director",
    "actors",
}


def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", "", text)
    return text.strip()


def to_snake_column(value: Any) -> str:
    normalized = normalize_header(value)
    if normalized in COLUMN_MAP:
        return COLUMN_MAP[normalized]
    text = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", normalized).strip("_").lower()
    return text or "unknown"


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if text in {"", "-", "nan", "NaN", "None"}:
        return None
    return text


def clean_movie_name(value: Any) -> Optional[str]:
    text = clean_text(value)
    if text is None:
        return None
    return re.sub(r"\s+", " ", text)


def clean_integer(value: Any) -> Optional[int]:
    text = clean_text(value)
    if text is None:
        return None
    text = text.replace(",", "")
    text = re.sub(r"[^0-9.-]", "", text)
    if text in {"", "-", ".", "-."}:
        return None
    return int(float(text))


def clean_float(value: Any) -> Optional[float]:
    text = clean_text(value)
    if text is None:
        return None
    text = text.replace(",", "").replace("%", "")
    text = re.sub(r"[^0-9.-]", "", text)
    if text in {"", "-", ".", "-."}:
        return None
    return float(text)


def clean_date(value: Any) -> Optional[str]:
    text = clean_text(value)
    if text is None:
        return None
    text = text.replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return None


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in record.items():
        column = to_snake_column(key)
        if column in INTEGER_COLUMNS:
            cleaned[column] = clean_integer(value)
        elif column == "sales_share":
            cleaned[column] = clean_float(value)
        elif column == "release_date":
            cleaned[column] = clean_date(value)
        elif column in TEXT_COLUMNS:
            cleaned[column] = clean_text(value)
        else:
            cleaned[column] = clean_text(value)

    cleaned["movie_name_clean"] = clean_movie_name(cleaned.get("movie_name"))
    return cleaned
