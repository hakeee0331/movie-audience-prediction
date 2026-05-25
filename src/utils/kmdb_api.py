from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from .cleaner import clean_date, clean_text


BASE_URL = "http://api.koreafilm.or.kr/openapi-data2/wisenut/search_api/search_json2.jsp"


@dataclass
class KmdbMatchResult:
    status: str
    rule: str | None
    score: float
    kmdb_movie_id: str | None
    kmdb_movie_seq: str | None
    kmdb_doc_id: str | None
    title: str | None
    release_date: str | None
    candidate_count: int
    raw_response_json: str
    matched_record_json: str | None
    error_message: str | None = None


class KmdbApiClient:
    def __init__(self, api_key: str, sleep_seconds: float = 0.15) -> None:
        self.api_key = api_key
        self.sleep_seconds = sleep_seconds

    def search_movies(self, movie_name: str, list_count: int = 10) -> dict[str, Any]:
        params = {
            "ServiceKey": self.api_key,
            "collection": "kmdb_new2",
            "detail": "Y",
            "query": movie_name,
            "listCount": str(list_count),
        }
        return self._get_json(params)

    def _get_json(self, params: dict[str, str]) -> dict[str, Any]:
        time.sleep(self.sleep_seconds)
        url = f"{BASE_URL}?{urlencode(params)}"
        with urlopen(url, timeout=20) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def choose_kmdb_match(movie_name: str, release_date: str, response: dict[str, Any]) -> KmdbMatchResult:
    raw_response_json = json.dumps(response, ensure_ascii=False)
    candidates = extract_results(response)
    if not candidates:
        return KmdbMatchResult("not_found", None, 0.0, None, None, None, None, None, 0, raw_response_json, None)

    target_title = normalize_title(movie_name)
    target_date = clean_date(release_date)
    target_year = release_date[:4] if release_date else None
    normalized_candidates = [
        {
            **candidate,
            "_title": normalize_title(candidate.get("title")),
            "_release_date": parse_kmdb_date(candidate.get("repRlsDate")),
        }
        for candidate in candidates
    ]

    exact_date = [
        candidate
        for candidate in normalized_candidates
        if candidate["_title"] == target_title and candidate["_release_date"] == target_date
    ]
    if len(exact_date) == 1:
        return _matched(exact_date[0], "exact_title_date", 1.0, len(candidates), raw_response_json)

    exact_title_year = [
        candidate
        for candidate in normalized_candidates
        if candidate["_title"] == target_title
        and candidate["_release_date"]
        and target_year
        and candidate["_release_date"][:4] == target_year
    ]
    if len(exact_title_year) == 1:
        return _matched(exact_title_year[0], "exact_title_year_single_candidate", 0.9, len(candidates), raw_response_json)

    exact_title = [candidate for candidate in normalized_candidates if candidate["_title"] == target_title]
    best = exact_title[0] if exact_title else normalized_candidates[0]
    status = "ambiguous" if exact_title else "candidate"
    return KmdbMatchResult(
        status=status,
        rule="needs_review",
        score=0.0,
        kmdb_movie_id=clean_text(best.get("movieId")),
        kmdb_movie_seq=clean_text(best.get("movieSeq")),
        kmdb_doc_id=clean_text(best.get("DOCID")),
        title=clean_kmdb_text(best.get("title")),
        release_date=best.get("_release_date"),
        candidate_count=len(candidates),
        raw_response_json=raw_response_json,
        matched_record_json=json.dumps(best, ensure_ascii=False),
    )


def parse_kmdb_detail(record_json: str | None) -> dict[str, Any]:
    record = json.loads(record_json) if record_json else {}
    return {
        "kmdb_movie_id": clean_text(record.get("movieId")),
        "kmdb_movie_seq": clean_text(record.get("movieSeq")),
        "kmdb_doc_id": clean_text(record.get("DOCID")),
        "title": clean_kmdb_text(record.get("title")),
        "title_en": clean_kmdb_text(record.get("titleEng")),
        "release_date": parse_kmdb_date(record.get("repRlsDate")),
        "countries": clean_kmdb_text(record.get("nation")),
        "genres": clean_kmdb_text(record.get("genre")),
        "directors": join_values(extract_people(record.get("directors"), ["directorNm", "peopleNm", "staffNm"])),
        "actors": join_values(extract_people(record.get("actors"), ["actorNm", "peopleNm", "staffNm"])),
        "production_companies": clean_kmdb_text(record.get("company")),
        "distributors": None,
        "ratings": clean_kmdb_text(record.get("rating")),
        "poster_url": first_poster_url(record.get("posters")),
        "synopsis": extract_synopsis(record.get("plots")),
        "raw_record_json": json.dumps(record, ensure_ascii=False),
        "fetched_at": utc_now(),
    }


def extract_results(response: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for data in response.get("Data", []):
        result = data.get("Result", [])
        if isinstance(result, list):
            results.extend(item for item in result if isinstance(item, dict))
    return results


def extract_people(value: Any, name_keys: list[str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        people: list[str] = []
        for key in name_keys:
            if key in value:
                text = clean_person_name(value.get(key))
                if text:
                    people.append(text)
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                people.extend(extract_people(nested, name_keys))
        return people
    if isinstance(value, list):
        people = []
        for item in value:
            people.extend(extract_people(item, name_keys))
        return people
    return []


def clean_person_name(value: Any) -> str | None:
    text = clean_kmdb_text(value)
    if text is None:
        return None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    for part in parts:
        if not re.fullmatch(r"\d+", part):
            return part
    return parts[0] if parts else None


def parse_kmdb_date(value: Any) -> str | None:
    text = clean_kmdb_text(value)
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 8:
        return clean_date(digits[:8])
    return clean_date(text)


def normalize_title(value: Any) -> str:
    text = clean_kmdb_text(value) or ""
    return "".join(text.split()).lower()


def clean_kmdb_text(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    text = re.sub(r"!HS|!HE", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def join_values(values: list[str]) -> str | None:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_kmdb_text(value)
        if text and text not in seen:
            cleaned.append(text)
            seen.add(text)
    return ",".join(cleaned) if cleaned else None


def first_poster_url(value: Any) -> str | None:
    text = clean_kmdb_text(value)
    if text is None:
        return None
    for url in text.split("|"):
        url = url.strip()
        if url:
            return url
    return None


def extract_synopsis(value: Any) -> str | None:
    plots = extract_plot_items(value)
    if not plots:
        return None

    for plot in plots:
        lang = clean_kmdb_text(plot.get("plotLang")) if isinstance(plot, dict) else None
        text = clean_kmdb_text(plot.get("plotText")) if isinstance(plot, dict) else None
        if text and lang == "한국어":
            return text

    for plot in plots:
        if isinstance(plot, dict):
            text = clean_kmdb_text(plot.get("plotText"))
            if text:
                return text
    return None


def extract_plot_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        plot = value.get("plot")
        if isinstance(plot, list):
            return [item for item in plot if isinstance(item, dict)]
        if isinstance(plot, dict):
            return [plot]
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _matched(candidate: dict[str, Any], rule: str, score: float, candidate_count: int, raw_response_json: str) -> KmdbMatchResult:
    return KmdbMatchResult(
        status="matched",
        rule=rule,
        score=score,
        kmdb_movie_id=clean_text(candidate.get("movieId")),
        kmdb_movie_seq=clean_text(candidate.get("movieSeq")),
        kmdb_doc_id=clean_text(candidate.get("DOCID")),
        title=clean_kmdb_text(candidate.get("title")),
        release_date=candidate.get("_release_date"),
        candidate_count=candidate_count,
        raw_response_json=raw_response_json,
        matched_record_json=json.dumps(candidate, ensure_ascii=False),
    )
