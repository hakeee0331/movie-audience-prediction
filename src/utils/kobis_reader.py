from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from .cleaner import clean_record, normalize_header


REQUIRED_HEADERS = {"영화명", "개봉일", "누적관객수"}


@dataclass
class KobisTable:
    rows: list[dict[str, Any]]
    period_start: str | None
    period_end: str | None


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._in_cell = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            text = " ".join("".join(self._current_cell).split())
            self._current_row.append(text)
            self._current_cell = None
            self._in_cell = False
        elif tag == "tr" and self._current_table is not None and self._current_row is not None:
            if any(cell.strip() for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._current_cell is not None:
            self._current_cell.append(data)


def read_kobis_file(path: Path) -> KobisTable:
    path = Path(path)
    raw_bytes = path.read_bytes()
    period_start, period_end = extract_period(path.name, raw_bytes)

    if _looks_like_html(raw_bytes):
        rows = _read_html_table(raw_bytes)
    else:
        rows = _read_excel_table(path)

    for idx, row in enumerate(rows, start=1):
        row["source_file"] = path.name
        row["period_start"] = period_start
        row["period_end"] = period_end
        row["row_number_in_file"] = idx

    return KobisTable(rows=rows, period_start=period_start, period_end=period_end)


def read_kobis_files(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(paths):
        records.extend(read_kobis_file(path).rows)
    return records


def extract_period(filename: str, raw_bytes: bytes | None = None) -> tuple[str | None, str | None]:
    candidates = [filename]
    if raw_bytes:
        text = raw_bytes[:20000].decode("utf-8", errors="ignore")
        candidates.append(text)

    for text in candidates:
        match = re.search(r"(\d{4}-\d{2}-\d{2})\s*[~\-]\s*(\d{4}-\d{2}-\d{2})", text)
        if match:
            return match.group(1), match.group(2)
    return None, None


def _looks_like_html(raw_bytes: bytes) -> bool:
    head = raw_bytes[:4096].lower()
    return b"<html" in head or b"<table" in head


def _read_html_table(raw_bytes: bytes) -> list[dict[str, Any]]:
    text = raw_bytes.decode("utf-8", errors="ignore")
    parser = _TableParser()
    parser.feed(text)

    for table in parser.tables:
        header_idx = _find_header_index(table)
        if header_idx is None:
            continue
        headers = table[header_idx]
        data_rows = table[header_idx + 1 :]
        return _records_from_rows(headers, data_rows)

    raise ValueError("KOBIS data table not found in HTML file.")


def _read_excel_table(path: Path) -> list[dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError(
            "Reading real Excel files requires pandas/openpyxl. Install dependencies with `pip install -r requirements.txt`."
        ) from exc

    frames = pd.read_excel(path, sheet_name=None, header=None)
    for frame in frames.values():
        rows = frame.fillna("").astype(str).values.tolist()
        header_idx = _find_header_index(rows)
        if header_idx is None:
            continue
        headers = rows[header_idx]
        data_rows = rows[header_idx + 1 :]
        return _records_from_rows(headers, data_rows)

    raise ValueError(f"KOBIS data table not found in Excel file: {path}")


def _find_header_index(rows: list[list[Any]]) -> int | None:
    for idx, row in enumerate(rows):
        normalized = {normalize_header(cell) for cell in row}
        if REQUIRED_HEADERS.issubset(normalized):
            return idx
    return None


def _records_from_rows(headers: list[Any], rows: list[list[Any]]) -> list[dict[str, Any]]:
    clean_headers = [normalize_header(header) for header in headers]
    records: list[dict[str, Any]] = []

    for row in rows:
        if not any(str(cell).strip() for cell in row):
            continue
        values = list(row[: len(clean_headers)])
        if len(values) < len(clean_headers):
            values.extend([""] * (len(clean_headers) - len(values)))
        raw_record = dict(zip(clean_headers, values))
        cleaned = clean_record(raw_record)
        if cleaned.get("movie_name_clean") and cleaned.get("release_date"):
            records.append(cleaned)

    return records
