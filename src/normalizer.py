from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
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
    if _is_kb_card_summary_row(row):
        return "kb_card_summary"
    if _is_kb_point_expiry_row(row):
        return "kb_point_expiry"
    if _is_benefit_usage_row(row):
        return "benefit_usage"
    if _is_dateless_benefit_adjustment(row):
        return "dateless_benefit_adjustment"
    if _has_invalid_date_cell(row):
        return "invalid_date"
    if _has_misaligned_amount_review(row):
        return "misaligned_amount"
    return ""


def _is_kb_card_summary_row(row: dict[str, Any]) -> bool:
    header = [re.sub(r"\s+", "", str(value)) for value in row.get("raw", {}).get("header", [])]
    if not {"이용자", "이용카드", "카드상품명", "이번달결제금액"}.issubset(set(header)):
        return False
    cells = [str(value).strip() for value in row.get("raw", {}).get("cells", [])]
    if len(cells) < 4:
        return False
    return bool(_parse_amount(cells[3]))


def _is_kb_point_expiry_row(row: dict[str, Any]) -> bool:
    header = [re.sub(r"\s+", "", str(value)) for value in row.get("raw", {}).get("header", [])]
    cells = [str(value).strip() for value in row.get("raw", {}).get("cells", [])]
    return bool(header and "소멸예정일" in header[0] and cells and "포인트리" in cells[0])


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


def _is_dateless_benefit_adjustment(row: dict[str, Any]) -> bool:
    cells = [str(value).strip() for value in row.get("raw", {}).get("cells", [])]
    if not cells or cells[0]:
        return False
    joined = " ".join(cells)
    if not any(keyword in joined for keyword in ("포인트사용", "M포인트", "할인", "캐시백")):
        return False
    return any(_parse_amount(cell) is not None for cell in cells)


def _is_benefit_usage_row(row: dict[str, Any]) -> bool:
    cells = [str(value).strip() for value in row.get("raw", {}).get("cells", [])]
    joined = " ".join(cells)
    if not any(keyword in joined for keyword in ("M포인트 사용", "M포인트사용", "바우처", "포인트사용혜택")):
        return False
    money_values = [_parse_amount(cell) for cell in cells]
    return any(isinstance(value, int) for value in money_values)


def _exclude_normalized_duplicates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for key in _normalized_duplicate_keys(row):
            grouped[key].append(row)

    excluded: set[tuple[str, int]] = _guard_duplicate_source_keys(rows) | _guard_low_confidence_source_keys(rows)
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
            if not _normalized_duplicate_merchants_match(page_rows):
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


def _guard_duplicate_source_keys(rows: list[dict[str, Any]]) -> set[tuple[str, int]]:
    regular_keys: set[tuple[Any, ...]] = set()
    for row in rows:
        if _is_guard_chunk(row):
            continue
        for key in _guard_comparison_keys(row):
            regular_keys.add(key)

    excluded: set[tuple[str, int]] = set()
    for row in rows:
        if not _is_guard_chunk(row):
            continue
        if any(key in regular_keys for key in _guard_comparison_keys(row)):
            excluded.add(_source_key(row))
    return excluded


def _guard_low_confidence_source_keys(rows: list[dict[str, Any]]) -> set[tuple[str, int]]:
    excluded: set[tuple[str, int]] = set()
    for row in rows:
        if not _is_guard_chunk(row):
            continue
        transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
        quality = row.get("quality", {}) if isinstance(row.get("quality"), dict) else {}
        date_value = str(transaction.get("date", "")).strip()
        merchant = str(transaction.get("merchant", "")).strip()
        amount = transaction.get("amount")
        billing_amount = transaction.get("billing_amount")
        if not _is_valid_date_like(date_value):
            excluded.add(_source_key(row))
            continue
        if not isinstance(amount, int) and not isinstance(billing_amount, int):
            excluded.add(_source_key(row))
            continue
        if merchant.startswith("ETC.") or merchant in {"기타", "?기타"}:
            excluded.add(_source_key(row))
            continue
        if quality.get("needs_review"):
            excluded.add(_source_key(row))
    return excluded


def _guard_comparison_keys(row: dict[str, Any]) -> list[tuple[Any, ...]]:
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
    date = str(transaction.get("date", "")).strip()
    if not date:
        return []
    amount = transaction.get("amount")
    billing_amount = transaction.get("billing_amount")
    amounts = [value for value in (amount, billing_amount) if isinstance(value, int)]
    return [("guard", int(source.get("page", 0) or 0), date, value) for value in set(amounts)]


def _is_guard_chunk(row: dict[str, Any]) -> bool:
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    index = _chunk_index(str(source.get("chunk_id", "")))
    return isinstance(index, int) and index >= 80


def _normalized_duplicate_merchants_match(rows: list[dict[str, Any]]) -> bool:
    if any(_has_merchant_ocr_review(row) for row in rows):
        return True
    merchant_keys = []
    for row in rows:
        transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
        merchant_key = _normalized_duplicate_merchant_key(transaction.get("merchant"))
        if merchant_key:
            merchant_keys.append(merchant_key)
    if len(merchant_keys) < 2:
        return False
    first = merchant_keys[0]
    return all(_normalized_duplicate_merchant_match(first, key) for key in merchant_keys)


def _has_merchant_ocr_review(row: dict[str, Any]) -> bool:
    quality = row.get("quality", {}) if isinstance(row.get("quality"), dict) else {}
    reason = str(quality.get("review_reason", "")).lower()
    return bool(quality.get("needs_review")) and "merchant" in reason and "ocr" in reason


def _normalized_duplicate_merchant_match(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) >= 4 and (left in right or right in left):
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.78


def _normalized_duplicate_merchant_key(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").lower())
    return re.sub(r"\W+", "", text, flags=re.UNICODE)


def _looks_like_normalized_overlap(chunk_numbers: list[int]) -> bool:
    if not chunk_numbers:
        return False
    if len(set(chunk_numbers)) < 2:
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

    repaired = _repair_hyundai_shifted_rows(transaction, extra_fields, header, cells)
    kb_repaired = _repair_kb_short_billing_row(transaction, header, cells)
    shinhan_repaired = _repair_shinhan_amount_rows(transaction, cells)
    review_reasons = _filter_auto_resolved_reasons(review_reasons, transaction, cells)
    if repaired or shinhan_repaired or kb_repaired:
        review_reasons = _filter_repaired_hyundai_reasons(review_reasons)

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


def _repair_shinhan_amount_rows(transaction: dict[str, Any], cells: list[str]) -> bool:
    if len(cells) < 6:
        return False
    primary_amount = _parse_amount(cells[3])
    if primary_amount is None and len(cells) > 4:
        primary_amount = _parse_amount(cells[4])
    if primary_amount is None:
        return False
    amount = transaction.get("amount")
    source_text = cells[5].strip()
    if amount == 0 and primary_amount != 0:
        transaction["amount"] = primary_amount
        return True
    if isinstance(amount, int) and abs(amount) > 100_000_000 and "/" in source_text:
        transaction["amount"] = primary_amount
        return True
    return False


def _repair_kb_short_billing_row(transaction: dict[str, Any], header: list[str], cells: list[str]) -> bool:
    normalized_header = [re.sub(r"\s+", "", str(value)) for value in header]
    if not {"이용카드", "이용일", "이용가맹점", "이용금액", "현지금액", "이번달결제금액"}.issubset(set(normalized_header)):
        return False
    if len(cells) != 6 or transaction.get("billing_amount") is not None:
        return False
    amount = transaction.get("amount")
    billing_amount = _parse_amount(cells[5])
    if not isinstance(amount, int) or billing_amount is None:
        return False
    transaction["billing_amount"] = billing_amount
    return True


def _repair_hyundai_shifted_rows(
    transaction: dict[str, Any],
    extra_fields: dict[str, Any],
    header: list[str],
    cells: list[str],
) -> bool:
    repaired = _repair_hyundai_billing_amount_from_header(transaction, header, cells)
    if _repair_hyundai_combined_date_card_header(transaction, extra_fields, header, cells):
        return True
    if _repair_hyundai_highpass_count_row(transaction, cells):
        return True
    if _repair_hyundai_actual_principal_row(transaction, header, cells):
        return True
    if _repair_hyundai_split_content_row(transaction, cells):
        return True
    if _repair_hyundai_owner_card_row(transaction, extra_fields, cells):
        return True
    if _repair_hyundai_amount_shift_row(transaction, header, cells):
        return True
    if _repair_hyundai_direct_amount_row(transaction, cells):
        return True
    return _repair_hyundai_small_amount_with_billing(transaction) or repaired


def _repair_hyundai_billing_amount_from_header(
    transaction: dict[str, Any],
    header: list[str],
    cells: list[str],
) -> bool:
    if transaction.get("billing_amount") is not None:
        return False
    for index, label in enumerate(header):
        normalized = re.sub(r"\s+", "", str(label))
        if normalized not in {"결제원금", "결제원금(원)", "청구금액"}:
            continue
        if index >= len(cells):
            continue
        billing_amount = _parse_amount(cells[index])
        if billing_amount is None:
            continue
        transaction["billing_amount"] = billing_amount
        return True
    return False


def _repair_hyundai_split_content_row(transaction: dict[str, Any], cells: list[str]) -> bool:
    if len(cells) < 7:
        return False
    card_label = cells[1].strip()
    if not _looks_like_date_token(cells[0]) or not card_label.startswith("본인 "):
        return False
    if not any(token in card_label.lower() for token in ("purple", "zero", "퍼플")):
        return False
    amount = _parse_amount(cells[3])
    billing_amount = _parse_amount(cells[-1])
    if amount is None:
        return False
    transaction["date"] = _normalize_date(cells[0])
    transaction["card_label"] = card_label
    transaction["merchant"] = cells[2].strip()
    transaction["amount"] = amount
    if billing_amount is not None:
        transaction["billing_amount"] = billing_amount
    transaction["transaction_type"] = ""
    return True


def _repair_hyundai_highpass_count_row(transaction: dict[str, Any], cells: list[str]) -> bool:
    if len(cells) < 5 or not _looks_like_date_token(cells[0]):
        return False
    card_label = cells[1].strip()
    if "하이패스" not in card_label and "?섏씠?⑥뒪" not in card_label:
        return False
    if not re.fullmatch(r"\d{3,4}(건|嫄?)", cells[3].strip()):
        return False
    amount_values = [
        amount
        for amount in (_parse_amount(cell) for cell in cells)
        if isinstance(amount, int) and abs(amount) >= 1000
    ]
    if not amount_values:
        return False
    amount = amount_values[-1]
    transaction["date"] = _normalize_date(cells[0])
    transaction["card_label"] = card_label
    transaction["merchant"] = cells[2].strip()
    transaction["amount"] = amount
    transaction["billing_amount"] = amount
    transaction["transaction_type"] = ""
    return True


def _repair_hyundai_actual_principal_row(
    transaction: dict[str, Any],
    header: list[str],
    cells: list[str],
) -> bool:
    joined_header = "|".join(re.sub(r"\s+", "", str(value)) for value in header)
    if "실제원금" not in joined_header:
        return False
    if len(cells) < 5 or not _looks_like_date_token(cells[0]):
        return False
    amounts = [_parse_amount(cell) for cell in cells]
    amount_values = [amount for amount in amounts if isinstance(amount, int)]
    amount = amount_values[-1] if amount_values else None
    if amount is None:
        return False
    transaction["date"] = _normalize_date(cells[0])
    transaction["card_label"] = cells[1].strip()
    transaction["merchant"] = cells[2].strip()
    transaction["amount"] = amount
    transaction["billing_amount"] = amount
    transaction["transaction_type"] = ""
    return True


def _repair_hyundai_combined_date_card_header(
    transaction: dict[str, Any],
    extra_fields: dict[str, Any],
    header: list[str],
    cells: list[str],
) -> bool:
    if len(cells) < 8 or not header:
        return False
    first_header = re.sub(r"\s+", "", str(header[0]))
    if "이용일이용카드" not in first_header:
        return False
    if not _looks_like_date_token(cells[0]):
        return False
    amount = _parse_amount(cells[3])
    billing_amount = _parse_amount(cells[7])
    if amount is None:
        return False
    transaction["date"] = _normalize_date(cells[0])
    transaction["card_label"] = cells[1].strip()
    transaction["merchant"] = cells[2].strip()
    transaction["amount"] = amount
    if billing_amount is not None:
        transaction["billing_amount"] = billing_amount
    transaction["transaction_type"] = ""
    if len(cells) > 5 and cells[5].strip():
        extra_fields["discount"] = cells[5].strip()
    if len(cells) > 6 and cells[6].strip():
        extra_fields["points"] = cells[6].strip()
    return True


def _repair_hyundai_owner_card_row(
    transaction: dict[str, Any],
    extra_fields: dict[str, Any],
    cells: list[str],
) -> bool:
    if len(cells) < 8 or cells[1].strip() != "본인":
        return False

    card = cells[2].strip()
    if card.upper() == "ZERO" and len(cells) >= 9 and "포인트형" in cells[3]:
        card_label = "본인 ZERO 포인트형"
        merchant = cells[4].strip()
        amount_index = 5
    elif _looks_like_card_token(card):
        card_label = f"본인 {card}"
        merchant = cells[3].strip()
        amount_index = 4
    else:
        return False

    amount = _parse_amount(cells[amount_index])
    billing_amount = _parse_amount(cells[-1])
    if amount is None:
        return False

    transaction["card_label"] = card_label
    transaction["merchant"] = merchant
    transaction["amount"] = amount
    if billing_amount is not None:
        transaction["billing_amount"] = billing_amount
    transaction["transaction_type"] = ""
    if amount_index + 1 < len(cells) - 1 and cells[amount_index + 1].strip():
        extra_fields["적립률"] = cells[amount_index + 1].strip()
    if amount_index + 2 < len(cells) - 1 and cells[amount_index + 2].strip():
        extra_fields["points"] = cells[amount_index + 2].strip()
    return True


def _repair_hyundai_amount_shift_row(
    transaction: dict[str, Any],
    header: list[str],
    cells: list[str],
) -> bool:
    joined_header = "|".join(header)
    if "실제원금" not in joined_header and "할부/회차" not in joined_header:
        return False
    if transaction.get("amount") is not None or len(cells) < 5:
        return False
    amount = _parse_amount(cells[4])
    billing_amount = _parse_amount(cells[-1])
    if isinstance(amount, int) and isinstance(billing_amount, int) and abs(amount) < 1000 <= abs(billing_amount):
        amount = billing_amount
    if amount is None:
        return False
    transaction["amount"] = amount
    if billing_amount is not None:
        transaction["billing_amount"] = billing_amount
    if transaction.get("transaction_type") == cells[4]:
        transaction["transaction_type"] = ""
    return True


def _repair_hyundai_direct_amount_row(transaction: dict[str, Any], cells: list[str]) -> bool:
    if transaction.get("amount") is not None or len(cells) < 4:
        return False
    if not transaction.get("date") or not transaction.get("card_label") or not transaction.get("merchant"):
        return False
    amount = _parse_amount(cells[3])
    if amount is None:
        return False
    transaction["amount"] = amount
    if len(cells) >= 8:
        billing_amount = _parse_amount(cells[7])
        if billing_amount is not None:
            transaction["billing_amount"] = billing_amount
    return True


def _repair_hyundai_small_amount_with_billing(transaction: dict[str, Any]) -> bool:
    amount = transaction.get("amount")
    billing_amount = transaction.get("billing_amount")
    if not isinstance(amount, int) or not isinstance(billing_amount, int):
        return False
    if abs(amount) >= 1000 or abs(billing_amount) < 10000:
        return False
    transaction["amount"] = billing_amount
    return True


def _looks_like_card_token(value: str) -> bool:
    text = value.strip().lower()
    return bool(text) and any(token in text for token in ("purple", "zero", "카드", "포인트형", "하이패스"))


def _filter_repaired_hyundai_reasons(reasons: list[str]) -> list[str]:
    auto_resolved = (
        "열 매핑 확인 필요",
        "Column alignment is unclear",
        "Header misalignment",
        "value 12,000 appears",
        "amount 후보",
        "amount 값을 숫자로 읽지 못했습니다",
        "amount 일부 값을 숫자로 읽지 못했습니다",
        "merchant 후보",
        "가맹점 열을 확정하지 못했습니다",
        "이용금액을 숫자로 확정하지 못했습니다",
    )
    return [reason for reason in reasons if not any(token in reason for token in auto_resolved)]


def _filter_auto_resolved_reasons(
    reasons: list[str],
    transaction: dict[str, Any],
    cells: list[str],
) -> list[str]:
    filtered: list[str] = []
    for reason in reasons:
        if _is_samsung_repaired_shape(cells) and isinstance(transaction.get("amount"), int):
            if any(
                token in reason
                for token in (
                    "col_4",
                    "col_7",
                    "col_8",
                    "col_9",
                    "col_11",
                    "amount ",
                    "merchant ",
                    "열 매핑 확인 필요",
                )
            ):
                continue
        if _is_shinhan_amount_shape(cells) and isinstance(transaction.get("amount"), int):
            if any(token in reason for token in ("col_4", "col_6", "col_8", "col_10", "amount ", "Amount split", "Multiple entries", "dup_")):
                continue
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
        if any(token in reason for token in ("Formatting of negative row", "Potential typo", "Data alignment")) and (
            isinstance(transaction.get("amount"), int) or _amount_optional_transaction(transaction, cells)
        ):
            continue
        filtered.append(reason)
    return filtered


def _is_samsung_repaired_shape(cells: list[str]) -> bool:
    if len(cells) < 10:
        return False
    has_standard_amounts = _parse_amount(cells[3]) is not None and (
        _parse_amount(cells[6]) is not None or (len(cells) > 7 and _parse_amount(cells[7]) is not None)
    )
    has_split_card_amounts = len(cells) == 10 and _parse_amount(cells[4]) is not None and _parse_amount(cells[6]) is not None
    if not has_standard_amounts and not has_split_card_amounts:
        return False
    return bool(cells[1].strip())


def _is_shinhan_amount_shape(cells: list[str]) -> bool:
    if len(cells) < 6:
        return False
    return bool(cells[0].strip() and cells[1].strip() and cells[2].strip()) and (
        _parse_amount(cells[3]) is not None or _parse_amount(cells[4]) is not None or _parse_amount(cells[5]) is not None
    )


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
    match = re.fullmatch(r"(\d{2})(\d{2})", text)
    if match and _valid_date_parts("2000", *match.groups()):
        month, day = match.groups()
        return f"{int(month):02d}-{int(day):02d}"
    return text


def _looks_like_date_token(value: str) -> bool:
    return bool(
        re.fullmatch(r"\d{1,2}[./-]\d{1,2}", value)
        or re.fullmatch(r"\d{4}", value)
        or re.fullmatch(r"\d{2}[./-]\d{1,2}[./-]\d{1,2}", value)
        or re.fullmatch(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", value)
    )


def _is_valid_date_like(value: str) -> bool:
    text = value.strip()
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", text)
    if match:
        return _valid_date_parts("2000", *match.groups())
    match = re.fullmatch(r"(\d{2})(\d{2})", text)
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
        if field == "billing_amount" and _is_foreign_detail_billing_row(row):
            continue
        value = row.get("transaction", {}).get(field)
        if isinstance(value, int):
            total += value
    return total


def _is_foreign_detail_billing_row(row: dict[str, Any]) -> bool:
    raw = row.get("raw", {}) if isinstance(row.get("raw"), dict) else {}
    header = [re.sub(r"\s+", "", str(value)) for value in raw.get("header", [])]
    joined = "|".join(header)
    return "국가" in header and "해외이용금액" in joined and "결제원금(원)" in joined


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
