from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
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
    rows = _read_jsonl(merge_output.rows_merged_path)
    mapping_index = _mapping_index(mapping_output)
    transactions = [_normalize_row(row, mapping_index) for row in rows]

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
        "transaction_count": len(transactions),
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

    if not transaction.get("date"):
        review_reasons.append("날짜 열을 확정하지 못했습니다.")
    if not transaction.get("merchant"):
        review_reasons.append("가맹점 열을 확정하지 못했습니다.")
    if transaction.get("amount") is None:
        review_reasons.append("이용금액을 숫자로 확정하지 못했습니다.")

    normalized["transaction"] = transaction
    normalized["extra_fields"] = extra_fields
    normalized.setdefault("quality", {})
    normalized["quality"]["needs_review"] = bool(review_reasons)
    normalized["quality"]["review_reason"] = "; ".join(_unique(review_reasons))
    return normalized


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


def _normalize_date(value: str) -> str:
    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", text)
    if match:
        month, day = match.groups()
        return f"{int(month):02d}-{int(day):02d}"
    return text


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
