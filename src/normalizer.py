from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.profile_store import MappingOutput
from src.row_merger import RowMergeOutput


TEXT_FIELDS = {"date", "card_label", "merchant", "transaction_type"}
AMOUNT_FIELDS = {"amount", "billing_amount"}
CORE_FIELDS = TEXT_FIELDS | AMOUNT_FIELDS


@dataclass(frozen=True)
class NormalizationOutput:
    transactions_path: Path
    summary_path: Path
    transaction_count: int
    review_count: int
    amount_total: int
    billing_amount_total: int
    summary: dict[str, Any]


def build_transactions(
    merge_output: RowMergeOutput | None,
    mapping_output: MappingOutput | None,
    merged_dir: Path,
) -> NormalizationOutput | None:
    if not merge_output or not mapping_output or not merge_output.rows_merged_path.exists():
        return None

    merged_dir.mkdir(parents=True, exist_ok=True)
    source_rows = _read_jsonl(merge_output.rows_merged_path)
    exclusion_reasons = Counter(_row_exclusion_reason(row) for row in source_rows)
    rows = [row for row in source_rows if not _row_exclusion_reason(row)]
    mapping_index = _mapping_index(mapping_output)
    transactions_all = [_normalize_row(row, mapping_index) for row in rows]
    transactions, normalized_duplicate_excluded = _exclude_normalized_duplicates(transactions_all)
    duplicate_excluded_count = int(exclusion_reasons.get("duplicate_excluded", 0)) + normalized_duplicate_excluded

    transactions_path = merged_dir / "transactions.jsonl"
    summary_path = merged_dir / "normalization_summary.json"
    _write_jsonl(transactions_path, transactions)

    amount_total = _sum_amount(transactions, "amount")
    billing_total = _sum_amount(transactions, "billing_amount")
    review_rows = [row for row in transactions if row.get("quality", {}).get("needs_review")]
    reason_counts = Counter(
        reason
        for row in review_rows
        for reason in _split_reasons(str(row.get("quality", {}).get("review_reason", "")))
    )

    summary = {
        "schema_version": "1.0",
        "source_row_count": len(source_rows),
        "transaction_count": len(transactions),
        "duplicate_excluded_count": duplicate_excluded_count,
        "normalized_duplicate_excluded_count": normalized_duplicate_excluded,
        "invalid_date_excluded_count": int(exclusion_reasons.get("invalid_date", 0)),
        "review_count": len(review_rows),
        "amount_total": amount_total,
        "billing_amount_total": billing_total,
        "outputs": {
            "transactions": str(transactions_path),
            "source_rows": str(merge_output.rows_merged_path),
            "mapping_suggestions": str(mapping_output.suggestions_path),
        },
        "review_reason_counts": [
            {"reason": reason, "count": count}
            for reason, count in reason_counts.most_common(20)
        ],
        "review_samples": [_review_sample(row) for row in review_rows[:20]],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return NormalizationOutput(
        transactions_path=transactions_path,
        summary_path=summary_path,
        transaction_count=len(transactions),
        review_count=len(review_rows),
        amount_total=amount_total,
        billing_amount_total=billing_total,
        summary=summary,
    )


def _row_exclusion_reason(row: dict[str, Any]) -> str:
    merge = row.get("merge", {})
    if str(merge.get("decision", "keep")) == "duplicate_excluded":
        return "duplicate_excluded"
    if _has_invalid_date_cell(row):
        return "invalid_date"
    if _has_misaligned_amount_review(row):
        return "misaligned_amount"
    return ""


def _has_invalid_date_cell(row: dict[str, Any]) -> bool:
    cells = [str(value).strip() for value in row.get("raw", {}).get("cells", [])]
    if not cells or not cells[0]:
        return False
    return _looks_like_date_token(cells[0]) and not _is_valid_date_like(cells[0])


def _has_misaligned_amount_review(row: dict[str, Any]) -> bool:
    quality = row.get("quality", {}) if isinstance(row.get("quality"), dict) else {}
    if not quality.get("needs_review"):
        return False
    reason = str(quality.get("review_reason", "")).lower()
    return "misaligned" in reason or "truncated" in reason


def _exclude_normalized_duplicates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for key in _normalized_duplicate_keys(row):
            grouped[key].append(row)

    excluded: set[tuple[str, int]] = set()
    for candidates in grouped.values():
        by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in candidates:
            source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
            by_page[int(source.get("page", 0) or 0)].append(row)
        for page_rows in by_page.values():
            chunks = {_chunk_index(str(row.get("source", {}).get("chunk_id", ""))) for row in page_rows}
            chunk_numbers = sorted(index for index in chunks if index is not None)
            if len(page_rows) < 2 or not _looks_like_normalized_overlap(chunk_numbers):
                continue
            representative = max(page_rows, key=_normalized_representative_score)
            representative_key = _source_key(representative)
            for row in page_rows:
                row_key = _source_key(row)
                if row_key == representative_key:
                    continue
                excluded.add(row_key)

    kept: list[dict[str, Any]] = []
    for row in rows:
        if _source_key(row) in excluded:
            continue
        kept.append(row)
    return kept, len(excluded)


def _normalized_duplicate_keys(row: dict[str, Any]) -> list[tuple[Any, ...]]:
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
    amount = transaction.get("amount")
    if not isinstance(amount, int):
        return []
    date = str(transaction.get("date", "")).strip()
    if not date:
        return []
    billing_amount = transaction.get("billing_amount")
    billing_key = billing_amount if isinstance(billing_amount, int) else amount
    page = int(source.get("page", 0) or 0)
    keys: list[tuple[Any, ...]] = [("date_amount", page, date, amount, billing_key)]

    transaction_type = str(transaction.get("transaction_type", "")).strip()
    if re.fullmatch(r"\d+\s*/\s*\d+", transaction_type):
        original_amount = _original_amount(row)
        if isinstance(original_amount, int):
            keys.append(("installment_amount", page, transaction_type, original_amount, amount, billing_key))
    return keys


def _looks_like_normalized_overlap(chunk_numbers: list[int]) -> bool:
    if not chunk_numbers:
        return False
    span = chunk_numbers[-1] - chunk_numbers[0]
    return span <= 1 or (span <= 2 and len(set(chunk_numbers)) >= 2)


def _original_amount(row: dict[str, Any]) -> int | None:
    extra_fields = row.get("extra_fields", {}) if isinstance(row.get("extra_fields"), dict) else {}
    for key, value in extra_fields.items():
        if "이용금액" not in str(key):
            continue
        amount = _parse_amount(str(value))
        if isinstance(amount, int):
            return amount
    return None


def _normalized_representative_score(row: dict[str, Any]) -> tuple[int, int, int, int]:
    quality = row.get("quality", {}) if isinstance(row.get("quality"), dict) else {}
    cells = [str(value).strip() for value in row.get("raw", {}).get("cells", [])]
    transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    return (
        0 if quality.get("needs_review") else 1,
        1 if transaction.get("billing_amount") is not None else 0,
        sum(1 for cell in cells if cell),
        -int(source.get("local_row_index", 0) or 0),
    )


def _source_key(row: dict[str, Any]) -> tuple[str, int]:
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    return (str(source.get("chunk_id", "")), int(source.get("local_row_index", 0) or 0))


def _chunk_index(chunk_id: str) -> int | None:
    match = re.search(r"_chunk_(\d+)$", chunk_id)
    if not match:
        return None
    return int(match.group(1))


def load_normalization_output(merged_dir: Path) -> NormalizationOutput | None:
    transactions_path = merged_dir / "transactions.jsonl"
    summary_path = merged_dir / "normalization_summary.json"
    if not transactions_path.exists() or not summary_path.exists():
        return None

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return NormalizationOutput(
        transactions_path=transactions_path,
        summary_path=summary_path,
        transaction_count=int(summary.get("transaction_count", 0)),
        review_count=int(summary.get("review_count", 0)),
        amount_total=int(summary.get("amount_total", 0)),
        billing_amount_total=int(summary.get("billing_amount_total", 0)),
        summary=summary,
    )


def _normalize_row(
    row: dict[str, Any],
    mapping_index: dict[str, dict[int, dict[str, Any]]],
) -> dict[str, Any]:
    normalized = json.loads(json.dumps(row, ensure_ascii=False))
    header = [str(value) for value in normalized.get("raw", {}).get("header", [])]
    cells = [str(value) for value in normalized.get("raw", {}).get("cells", [])]
    column_map = mapping_index.get(_header_key(header), {})

    review_reasons = _split_reasons(str(normalized.get("quality", {}).get("review_reason", "")))
    field_values: dict[str, list[dict[str, Any]]] = defaultdict(list)
    extra_fields: dict[str, Any] = dict(normalized.get("extra_fields", {}))

    if not column_map:
        review_reasons.append("이 표의 열 매핑 정보를 찾지 못했습니다.")

    for index, value in enumerate(cells):
        value = value.strip()
        column = column_map.get(index)
        if not column:
            if value:
                extra_fields[f"unmapped_col_{index + 1}"] = value
            continue

        field = str(column.get("selected_field") or column.get("suggested_field") or "extra")
        if field == "ignore" or not value:
            continue

        if column.get("requires_review"):
            review_reasons.append(
                f"열 매핑 확인 필요: {column.get('column_id', f'col_{index + 1}')} {column.get('header', '')}".strip()
            )

        entry = {
            "value": value,
            "column_index": index,
            "column_id": column.get("column_id", f"col_{index + 1}"),
            "header": column.get("header", ""),
        }
        if field in CORE_FIELDS:
            field_values[field].append(entry)
        else:
            _put_extra(extra_fields, field, value, entry)

    transaction = dict(normalized.get("transaction", {}))
    for field in TEXT_FIELDS:
        value, reason = _choose_text(field, field_values.get(field, []))
        if reason:
            review_reasons.append(reason)
        transaction[field] = _normalize_date(value) if field == "date" else value

    for field in AMOUNT_FIELDS:
        amount, reason = _choose_amount(field, field_values.get(field, []))
        if reason:
            review_reasons.append(reason)
        transaction[field] = amount

    review_reasons = _filter_auto_resolved_reasons(review_reasons, transaction, cells)

    if not transaction.get("date"):
        review_reasons.append("날짜 열을 확정하지 못했습니다.")
    if not transaction.get("merchant"):
        review_reasons.append("가맹점 열을 확정하지 못했습니다.")
    if transaction.get("amount") is None and not _amount_optional_transaction(transaction, cells):
        review_reasons.append("이용금액을 숫자로 확정하지 못했습니다.")

    normalized["transaction"] = transaction
    normalized["extra_fields"] = extra_fields
    normalized.setdefault("quality", {})
    normalized["quality"]["needs_review"] = bool(review_reasons)
    normalized["quality"]["review_reason"] = "; ".join(_unique(review_reasons))
    return normalized


def _filter_auto_resolved_reasons(
    reasons: list[str],
    transaction: dict[str, Any],
    cells: list[str],
) -> list[str]:
    filtered: list[str] = []
    for reason in reasons:
        if _amount_optional_transaction(transaction, cells) and (
            "M 포인트 사용 행" in reason or "이용금액을 숫자로 확정하지 못했습니다" in reason
        ):
            continue
        if (
            "Extra column data" in reason
            and any(token in reason for token in ("할인", "적립", "points"))
            and isinstance(transaction.get("amount"), int)
        ):
            continue
        filtered.append(reason)
    return filtered


def _mapping_index(mapping_output: MappingOutput) -> dict[str, dict[int, dict[str, Any]]]:
    index: dict[str, dict[int, dict[str, Any]]] = {}
    for group in mapping_output.table_groups:
        header = [str(value) for value in group.get("header", [])]
        key = _header_key(header)
        columns: dict[int, dict[str, Any]] = {}
        for column in group.get("columns", []):
            if not isinstance(column, dict):
                continue
            columns[int(column.get("column_index", 0))] = column
        index[key] = columns
    return index


def _choose_text(field: str, values: list[dict[str, Any]]) -> tuple[str, str]:
    nonempty = [entry for entry in values if str(entry.get("value", "")).strip()]
    if not nonempty:
        return "", ""

    distinct = _unique([str(entry["value"]).strip() for entry in nonempty])
    reason = ""
    if len(distinct) > 1 and len(nonempty) > 1:
        reason = f"{field} 후보가 여러 열에서 발견되었습니다."
    return distinct[0], reason


def _choose_amount(field: str, values: list[dict[str, Any]]) -> tuple[int | None, str]:
    nonempty = [entry for entry in values if str(entry.get("value", "")).strip()]
    if not nonempty:
        return None, ""

    parsed: list[int] = []
    failed: list[str] = []
    for entry in nonempty:
        text = str(entry["value"]).strip()
        amount = _parse_amount(text)
        if amount is None:
            failed.append(text)
        else:
            parsed.append(amount)

    if not parsed:
        return None, f"{field} 값을 숫자로 읽지 못했습니다: {', '.join(failed[:3])}"

    reason = ""
    if failed:
        reason = f"{field} 일부 값을 숫자로 읽지 못했습니다: {', '.join(failed[:3])}"
    if len(set(parsed)) > 1:
        reason = f"{field} 후보 금액이 여러 열에서 다르게 발견되었습니다."
    return parsed[0], reason


def _parse_amount(value: str) -> int | None:
    text = str(value).strip()
    if not text:
        return None
    negative = bool(re.search(r"[-−△▲]", text) or (text.startswith("(") and text.endswith(")")))
    cleaned = re.sub(r"[^\d]", "", text)
    if not cleaned:
        return None
    amount = int(cleaned)
    return -amount if negative else amount


def _amount_optional_transaction(transaction: dict[str, Any], cells: list[str]) -> bool:
    merchant = str(transaction.get("merchant", "")).strip()
    amount = transaction.get("amount")
    if amount is not None:
        return False
    benefit_keywords = ("포인트사용", "포인트", "할인", "적립", "캐시백")
    if any(keyword in merchant for keyword in benefit_keywords) and any(_parse_amount(cell) is not None for cell in cells):
        return True
    billing_amount = transaction.get("billing_amount")
    if isinstance(billing_amount, int) and "usd" in " ".join(cells).lower():
        return True
    return False


def _normalize_date(value: str) -> str:
    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
    if match and _valid_date_parts(*match.groups()):
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    match = re.fullmatch(r"(\d{2})[./-](\d{1,2})[./-](\d{1,2})", text)
    if match and _valid_date_parts(str(2000 + int(match.group(1))), match.group(2), match.group(3)):
        year, month, day = match.groups()
        return f"{2000 + int(year):04d}-{int(month):02d}-{int(day):02d}"
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", text)
    if match and _valid_date_parts("2000", *match.groups()):
        month, day = match.groups()
        return f"{int(month):02d}-{int(day):02d}"
    return text


def _looks_like_date_token(value: str) -> bool:
    return bool(
        re.fullmatch(r"\d{1,2}[./-]\d{1,2}", value)
        or re.fullmatch(r"\d{2}[./-]\d{1,2}[./-]\d{1,2}", value)
        or re.fullmatch(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", value)
    )


def _is_valid_date_like(value: str) -> bool:
    text = value.strip()
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", text)
    if match:
        return _valid_date_parts("2000", *match.groups())
    match = re.fullmatch(r"(\d{2})[./-](\d{1,2})[./-](\d{1,2})", text)
    if match:
        return _valid_date_parts(str(2000 + int(match.group(1))), match.group(2), match.group(3))
    match = re.fullmatch(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
    if match:
        return _valid_date_parts(*match.groups())
    return False


def _valid_date_parts(year: str, month: str, day: str) -> bool:
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        return False
    return True


def _put_extra(
    extra_fields: dict[str, Any],
    field: str,
    value: str,
    entry: dict[str, Any],
) -> None:
    key = field
    if field == "extra":
        key = str(entry.get("header") or entry.get("column_id") or "extra")
    if key in extra_fields:
        existing = extra_fields[key]
        if isinstance(existing, list):
            existing.append(value)
        else:
            extra_fields[key] = [existing, value]
    else:
        extra_fields[key] = value


def _review_sample(row: dict[str, Any]) -> dict[str, Any]:
    source = row.get("source", {})
    return {
        "source": {
            "page": source.get("page"),
            "chunk_id": source.get("chunk_id"),
            "local_row_index": source.get("local_row_index"),
        },
        "transaction": row.get("transaction", {}),
        "review_reason": row.get("quality", {}).get("review_reason", ""),
        "cells": row.get("raw", {}).get("cells", []),
        "image_ref": row.get("raw", {}).get("image_ref", ""),
    }


def _sum_amount(rows: list[dict[str, Any]], field: str) -> int:
    total = 0
    for row in rows:
        value = row.get("transaction", {}).get(field)
        if isinstance(value, int):
            total += value
    return total


def _header_key(header: list[str]) -> str:
    if not header:
        return "unknown_header"
    return "|".join(_norm(value) for value in header)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value).strip().lower())


def _split_reasons(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
