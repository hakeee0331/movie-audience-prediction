from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from .cleaner import clean_date, clean_text


BASE_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie"


@dataclass
class MatchResult:
    status: str
    rule: str | None
    score: float
    movie_cd: str | None
    movie_nm: str | None
    open_dt: str | None
    candidate_count: int
    raw_response_json: str
    error_message: str | None = None


class KobisApiClient:
    def __init__(self, api_key: str, sleep_seconds: float = 0.15) -> None:
        self.api_key = api_key
        self.sleep_seconds = sleep_seconds

    def search_movie_list(self, movie_name: str, release_date: str | None) -> dict[str, Any]:
        params = {"key": self.api_key, "movieNm": movie_name}
        if release_date:
            year = release_date[:4]
            params["openStartDt"] = year
            params["openEndDt"] = year
        return self._get_json("searchMovieList.json", params)

    def search_movie_info(self, movie_cd: str) -> dict[str, Any]:
        return self._get_json("searchMovieInfo.json", {"key": self.api_key, "movieCd": movie_cd})

    def _get_json(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        time.sleep(self.sleep_seconds)
        url = f"{BASE_URL}/{endpoint}?{urlencode(params)}"
        with urlopen(url, timeout=20) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def choose_movie_match(movie_name: str, release_date: str, response: dict[str, Any]) -> MatchResult:
    raw_response_json = json.dumps(response, ensure_ascii=False)
    candidates = response.get("movieListResult", {}).get("movieList", [])
    if not candidates:
        return MatchResult(
            status="not_found",
            rule=None,
            score=0.0,
            movie_cd=None,
            movie_nm=None,
            open_dt=None,
            candidate_count=0,
            raw_response_json=raw_response_json,
        )

    target_title = normalize_title(movie_name)
    target_date = clean_date(release_date)
    target_year = release_date[:4] if release_date else None
    normalized_candidates = [
        {
            **candidate,
            "_title": normalize_title(candidate.get("movieNm")),
            "_open_dt": clean_date(candidate.get("openDt")),
        }
        for candidate in candidates
    ]

    exact_date = [
        candidate
        for candidate in normalized_candidates
        if candidate["_title"] == target_title and candidate["_open_dt"] == target_date
    ]
    if len(exact_date) == 1:
        return _matched(exact_date[0], "exact_title_date", 1.0, len(candidates), raw_response_json)

    exact_title_year = [
        candidate
        for candidate in normalized_candidates
        if candidate["_title"] == target_title
        and candidate["_open_dt"]
        and target_year
        and candidate["_open_dt"][:4] == target_year
    ]
    if len(exact_title_year) == 1:
        return _matched(
            exact_title_year[0],
            "exact_title_year_single_candidate",
            0.9,
            len(candidates),
            raw_response_json,
        )

    exact_title = [candidate for candidate in normalized_candidates if candidate["_title"] == target_title]
    status = "ambiguous" if exact_title else "candidate"
    best = exact_title[0] if exact_title else normalized_candidates[0]
    return MatchResult(
        status=status,
        rule="needs_review",
        score=0.0,
        movie_cd=clean_text(best.get("movieCd")),
        movie_nm=clean_text(best.get("movieNm")),
        open_dt=clean_date(best.get("openDt")),
        candidate_count=len(candidates),
        raw_response_json=raw_response_json,
    )


def parse_movie_detail(response: dict[str, Any]) -> dict[str, Any]:
    movie_info = response.get("movieInfoResult", {}).get("movieInfo", {})
    companies = movie_info.get("companys", [])
    production_companies = [
        company.get("companyNm")
        for company in companies
        if "제작" in str(company.get("companyPartNm", ""))
    ]
    distributors = [
        company.get("companyNm")
        for company in companies
        if "배급" in str(company.get("companyPartNm", ""))
    ]

    return {
        "kobis_movie_cd": clean_text(movie_info.get("movieCd")),
        "movie_name": clean_text(movie_info.get("movieNm")),
        "movie_name_en": clean_text(movie_info.get("movieNmEn")),
        "open_date": clean_date(movie_info.get("openDt")),
        "countries": join_names(movie_info.get("nations", []), "nationNm"),
        "genres": join_names(movie_info.get("genres", []), "genreNm"),
        "directors": join_names(movie_info.get("directors", []), "peopleNm"),
        "actors": join_names(movie_info.get("actors", []), "peopleNm"),
        "production_companies": join_values(production_companies),
        "distributors": join_values(distributors),
        "ratings": join_names(movie_info.get("audits", []), "watchGradeNm"),
        "raw_response_json": json.dumps(response, ensure_ascii=False),
        "fetched_at": utc_now(),
    }


def normalize_title(value: Any) -> str:
    text = clean_text(value) or ""
    return "".join(text.split()).lower()


def join_names(items: list[dict[str, Any]], key: str) -> str | None:
    return join_values(item.get(key) for item in items)


def join_values(values) -> str | None:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            cleaned.append(text)
            seen.add(text)
    return ",".join(cleaned) if cleaned else None


def _matched(
    candidate: dict[str, Any],
    rule: str,
    score: float,
    candidate_count: int,
    raw_response_json: str,
) -> MatchResult:
    return MatchResult(
        status="matched",
        rule=rule,
        score=score,
        movie_cd=clean_text(candidate.get("movieCd")),
        movie_nm=clean_text(candidate.get("movieNm")),
        open_dt=clean_date(candidate.get("openDt")),
        candidate_count=candidate_count,
        raw_response_json=raw_response_json,
    )
