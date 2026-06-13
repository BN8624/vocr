from __future__ import annotations

import json
import re
from hashlib import sha1
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.normalizer import NormalizationOutput
from src.vision_extractor import VisionResult


@dataclass(frozen=True)
class ValidationOutput:
    validated_transactions_path: Path
    issues_path: Path
    summary_path: Path
    transaction_count: int
    row_issue_count: int
    issue_row_count: int
    checksum_status: str
    checksum_difference: int | None
    summary: dict[str, Any]


def build_validation(
    normalization_output: NormalizationOutput | None,
    vision_results: list[VisionResult] | None,
    merged_dir: Path,
    expected_chunk_count: int | None = None,
    review_state: dict[str, Any] | None = None,
) -> ValidationOutput | None:
    if not normalization_output or not normalization_output.transactions_path.exists():
        return None

    merged_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_jsonl(normalization_output.transactions_path)
    source_totals = _source_total_candidates(vision_results or [])
    row_issues = _validate_rows(rows)
    column_quality = _column_quality(rows)
    checksum = _checksum_summary(
        amount_total=normalization_output.amount_total,
        billing_amount_total=normalization_output.billing_amount_total,
        rows=rows,
        source_totals=source_totals,
        processed_chunk_count=len(vision_results or []),
        expected_chunk_count=expected_chunk_count,
        review_state=review_state or {},
    )

    validated_rows = [_with_validation(row, row_issues.get(_row_key(row), [])) for row in rows]

    validated_path = merged_dir / "transactions_validated.jsonl"
    issues_path = merged_dir / "validation_issues.json"
    summary_path = merged_dir / "validation_summary.json"
    _write_jsonl(validated_path, validated_rows)

    issue_records = [
        _issue_record(row, issues)
        for row in rows
        if (issues := row_issues.get(_row_key(row), []))
    ]
    issues_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "row_issue_count": sum(len(issues) for issues in row_issues.values()),
                "issue_row_count": len(issue_records),
                "column_issue_count": int(column_quality.get("issue_count", 0)),
                "issues": issue_records,
                "column_quality": column_quality,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    reason_counts = Counter(issue["code"] for issues in row_issues.values() for issue in issues)
    summary = {
        "schema_version": "1.0",
        "transaction_count": len(rows),
        "row_issue_count": sum(len(issues) for issues in row_issues.values()),
        "issue_row_count": len(issue_records),
        "issue_counts": [
            {"code": code, "label": _issue_label(code), "count": count}
            for code, count in reason_counts.most_common()
        ],
        "column_quality": column_quality,
        "checksum": checksum,
        "outputs": {
            "validated_transactions": str(validated_path),
            "issues": str(issues_path),
            "normalization_summary": str(normalization_output.summary_path),
        },
        "review_samples": issue_records[:20],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return ValidationOutput(
        validated_transactions_path=validated_path,
        issues_path=issues_path,
        summary_path=summary_path,
        transaction_count=len(rows),
        row_issue_count=summary["row_issue_count"],
        issue_row_count=len(issue_records),
        checksum_status=str(checksum["status"]),
        checksum_difference=checksum.get("difference"),
        summary=summary,
    )


def load_validation_output(merged_dir: Path) -> ValidationOutput | None:
    validated_path = merged_dir / "transactions_validated.jsonl"
    issues_path = merged_dir / "validation_issues.json"
    summary_path = merged_dir / "validation_summary.json"
    if not validated_path.exists() or not issues_path.exists() or not summary_path.exists():
        return None

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    checksum = summary.get("checksum", {}) if isinstance(summary.get("checksum"), dict) else {}
    difference = checksum.get("difference")
    return ValidationOutput(
        validated_transactions_path=validated_path,
        issues_path=issues_path,
        summary_path=summary_path,
        transaction_count=int(summary.get("transaction_count", 0)),
        row_issue_count=int(summary.get("row_issue_count", 0)),
        issue_row_count=int(summary.get("issue_row_count", 0)),
        checksum_status=str(checksum.get("status", "unknown")),
        checksum_difference=difference if isinstance(difference, int) else None,
        summary=summary,
    )


def _validate_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    issues: dict[str, list[dict[str, str]]] = defaultdict(list)
    stable_counts = _stable_cell_counts(rows)

    for row in rows:
        key = _row_key(row)
        transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
        raw = row.get("raw", {}) if isinstance(row.get("raw"), dict) else {}
        header = [str(value) for value in raw.get("header", [])]
        cells = [str(value) for value in raw.get("cells", [])]
        header_key = _header_key(header)
        expected_count = stable_counts.get(header_key)

        date = str(transaction.get("date", "")).strip()
        merchant = str(transaction.get("merchant", "")).strip()
        card_label = str(transaction.get("card_label", "")).strip()
        amount = transaction.get("amount")
        billing_amount = transaction.get("billing_amount")

        if not _is_date_like(date):
            issues[key].append(_issue("date_not_date_like", f"날짜처럼 보이지 않습니다: {date or '(비어 있음)'}"))
        if not isinstance(amount, int):
            if not _is_benefit_only_row(transaction, cells) and not _is_foreign_billing_only_row(transaction, cells):
                issues[key].append(_issue("amount_not_numeric", "이용금액이 숫자가 아닙니다."))
        elif amount == 0:
            issues[key].append(_issue("amount_zero", "이용금액이 0입니다. 실제 0원 거래인지 확인이 필요합니다."))
        elif abs(amount) > 100_000_000:
            issues[key].append(_issue("amount_too_large", f"이용금액이 매우 큽니다: {amount:,}"))
        if billing_amount is not None and not isinstance(billing_amount, int):
            issues[key].append(_issue("billing_not_numeric", "결제/청구 금액이 숫자가 아닙니다."))
        if merchant and _mostly_numeric(merchant):
            issues[key].append(_issue("merchant_mostly_numeric", f"가맹점 값이 숫자 중심입니다: {merchant}"))
        if merchant and len(merchant) <= 1:
            issues[key].append(_issue("merchant_too_short", f"가맹점 값이 너무 짧습니다: {merchant}"))
        if card_label and _looks_like_merchant(card_label):
            issues[key].append(_issue("card_label_merchant_like", f"카드명 값이 가맹점처럼 보입니다: {card_label}"))
        if (
            expected_count is not None
            and len(cells) != expected_count
            and not _is_hyundai_repaired_shape(cells)
            and not _is_samsung_repaired_shape(cells)
        ):
            issues[key].append(
                _issue(
                    "row_cell_count_unstable",
                    f"이 표의 보통 열 수는 {expected_count}개인데 이 행은 {len(cells)}개입니다.",
                )
            )

    return dict(issues)


def _stable_cell_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    grouped: dict[str, Counter[int]] = defaultdict(Counter)
    for row in rows:
        raw = row.get("raw", {}) if isinstance(row.get("raw"), dict) else {}
        header = [str(value) for value in raw.get("header", [])]
        cells = [str(value) for value in raw.get("cells", [])]
        grouped[_header_key(header)][len(cells)] += 1

    stable: dict[str, int] = {}
    for header_key, counts in grouped.items():
        if not counts:
            continue
        cell_count, frequency = counts.most_common(1)[0]
        if frequency >= 2:
            stable[header_key] = cell_count
    return stable


def _column_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        raw = row.get("raw", {}) if isinstance(row.get("raw"), dict) else {}
        header = [str(value) for value in raw.get("header", [])]
        grouped[_header_key(header)].append(row)

    groups = [_column_quality_group(group_id, group_rows) for group_id, group_rows in grouped.items()]
    issues = [
        issue
        for group in groups
        for issue in group.get("issues", [])
        if isinstance(issue, dict)
    ]
    return {
        "schema_version": "1.0",
        "issue_count": len(issues),
        "issues": issues,
        "groups": groups,
    }


def _column_quality_group(group_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    row_count = len(rows)
    raw_headers = _first_header(rows)
    metrics = {
        "date_parse_success_rate": _rate(rows, lambda row: _is_date_like(_transaction_text(row, "date"))),
        "amount_parse_success_rate": _rate(rows, _amount_valid_or_exempt),
        "merchant_numeric_like_rate": _rate(rows, lambda row: _mostly_numeric(_transaction_text(row, "merchant"))),
        "merchant_empty_rate": _rate(rows, lambda row: not _transaction_text(row, "merchant")),
        "merchant_unique_rate": _unique_rate(rows, "merchant"),
        "card_label_unique_count": _unique_count(rows, "card_label"),
        "card_label_long_text_rate": _rate(
            rows,
            lambda row: len(_transaction_text(row, "card_label")) >= 18
            and not _looks_like_card_label(_transaction_text(row, "card_label")),
        ),
        "row_cell_count_distribution": _cell_count_distribution(rows),
    }
    issues = _column_quality_issues(group_id, row_count, raw_headers, metrics)
    return {
        "group_id": group_id,
        "row_count": row_count,
        "header": raw_headers,
        "metrics": metrics,
        "issues": issues,
    }


def _column_quality_issues(
    group_id: str,
    row_count: int,
    header: list[str],
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if row_count < 2:
        return issues

    date_rate = float(metrics["date_parse_success_rate"])
    amount_rate = float(metrics["amount_parse_success_rate"])
    merchant_numeric_rate = float(metrics["merchant_numeric_like_rate"])
    merchant_empty_rate = float(metrics["merchant_empty_rate"])
    card_unique_count = int(metrics["card_label_unique_count"])
    card_unique_rate = card_unique_count / row_count if row_count else 0.0
    card_long_rate = float(metrics["card_label_long_text_rate"])
    distribution = metrics["row_cell_count_distribution"]
    dominant_count = int(distribution.get("dominant_count", 0))
    dominant_rate = int(distribution.get("dominant_frequency", 0)) / row_count if row_count else 1.0

    if date_rate < 0.8:
        issues.append(
            _column_issue(
                "date_parse_success_rate_low",
                "날짜 열 성공률이 낮습니다.",
                group_id,
                header,
                "date",
                date_rate,
                0.8,
            )
        )
    if amount_rate < 0.9:
        issues.append(
            _column_issue(
                "amount_parse_success_rate_low",
                "이용금액 열 성공률이 낮습니다.",
                group_id,
                header,
                "amount",
                amount_rate,
                0.9,
            )
        )
    if merchant_numeric_rate >= 0.3:
        issues.append(
            _column_issue(
                "merchant_numeric_like_rate_high",
                "가맹점 열에 숫자처럼 보이는 값이 많습니다.",
                group_id,
                header,
                "merchant",
                merchant_numeric_rate,
                0.3,
            )
        )
    if merchant_empty_rate >= 0.2:
        issues.append(
            _column_issue(
                "merchant_empty_rate_high",
                "가맹점 열의 빈 값 비율이 높습니다.",
                group_id,
                header,
                "merchant",
                merchant_empty_rate,
                0.2,
            )
        )
    if (card_unique_count >= 5 and card_unique_rate >= 0.7) or card_long_rate >= 0.4:
        issues.append(
            _column_issue(
                "card_label_column_contaminated",
                "카드명 열의 고유값/긴 텍스트 비율이 높아 가맹점과 섞였을 수 있습니다.",
                group_id,
                header,
                "card_label",
                {"unique_count": card_unique_count, "unique_rate": round(card_unique_rate, 3), "long_text_rate": card_long_rate},
                {"unique_count": 5, "unique_rate": 0.7, "long_text_rate": 0.4},
            )
        )
    if dominant_count and dominant_rate < 0.8:
        issues.append(
            _column_issue(
                "row_cell_count_distribution_unstable",
                "행별 셀 개수 분포가 불안정합니다.",
                group_id,
                header,
                "raw.cells",
                round(dominant_rate, 3),
                0.8,
            )
        )
    return issues


def _column_issue(
    code: str,
    message: str,
    group_id: str,
    header: list[str],
    field: str,
    value: Any,
    threshold: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": _issue_label(code),
        "message": message,
        "group_id": group_id,
        "header": header,
        "field": field,
        "value": value,
        "threshold": threshold,
    }


def _first_header(rows: list[dict[str, Any]]) -> list[str]:
    for row in rows:
        raw = row.get("raw", {}) if isinstance(row.get("raw"), dict) else {}
        header = [str(value) for value in raw.get("header", [])]
        if header:
            return header
    return []


def _rate(rows: list[dict[str, Any]], predicate: Any) -> float:
    if not rows:
        return 1.0
    return round(sum(1 for row in rows if predicate(row)) / len(rows), 3)


def _unique_count(rows: list[dict[str, Any]], field: str) -> int:
    return len({_transaction_text(row, field) for row in rows if _transaction_text(row, field)})


def _unique_rate(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    return round(_unique_count(rows, field) / len(rows), 3)


def _cell_count_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[int] = Counter()
    for row in rows:
        raw = row.get("raw", {}) if isinstance(row.get("raw"), dict) else {}
        cells = [str(value) for value in raw.get("cells", [])]
        counts[len(cells)] += 1
    dominant_count, dominant_frequency = counts.most_common(1)[0] if counts else (0, 0)
    return {
        "counts": {str(key): value for key, value in sorted(counts.items())},
        "dominant_count": dominant_count,
        "dominant_frequency": dominant_frequency,
    }


def _transaction_text(row: dict[str, Any], field: str) -> str:
    value = _transaction_value(row, field)
    return str(value).strip() if value is not None else ""


def _transaction_value(row: dict[str, Any], field: str) -> Any:
    transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
    return transaction.get(field)


def _source_total_candidates(vision_results: list[VisionResult]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for result in vision_results:
        data = result.data if result.data else {}
        totals = data.get("totals", []) if isinstance(data, dict) else []
        for total in totals:
            if not isinstance(total, dict):
                continue
            amount = _parse_amount(total.get("amount", total.get("value_text", "")))
            if amount is None:
                continue
            label = str(total.get("label", "") or total.get("value_text", "") or "원본 합계")
            if not _is_probable_source_total(label, total):
                continue
            key = (label, amount)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "id": _total_id(label, amount, result.page_number, result.chunk_id),
                    "label": label,
                    "value_text": str(total.get("value_text", "")),
                    "amount": amount,
                    "chunk_id": result.chunk_id,
                    "page": result.page_number,
                    "needs_review": bool(total.get("needs_review", False)),
                    "review_reason": str(total.get("review_reason", "")),
                }
            )
    return candidates


def _checksum_summary(
    amount_total: int,
    billing_amount_total: int,
    rows: list[dict[str, Any]],
    source_totals: list[dict[str, Any]],
    processed_chunk_count: int,
    expected_chunk_count: int | None,
    review_state: dict[str, Any],
) -> dict[str, Any]:
    expected = expected_chunk_count or processed_chunk_count
    is_complete_scan = expected <= 0 or processed_chunk_count >= expected
    scan_note = {
        "processed_chunk_count": processed_chunk_count,
        "expected_chunk_count": expected,
        "is_complete_scan": is_complete_scan,
    }

    selected_total_id = _selected_total_id(review_state)
    selected_total = _find_selected_total(source_totals, selected_total_id)
    basis_totals = _checksum_basis_targets(rows)
    auto_matches = _auto_match_candidates(amount_total, billing_amount_total, rows, source_totals)

    if not source_totals:
        if not is_complete_scan:
            return {
                "status": "incomplete_source_scan",
                "message": (
                    f"전체 {expected}개 청크 중 {processed_chunk_count}개만 Vision 결과가 있어 "
                    "뒤 페이지의 합계를 아직 못 봤을 수 있습니다."
                ),
                "amount_total": amount_total,
                "billing_amount_total": billing_amount_total,
                "basis_totals": basis_totals,
                "source_total_candidates": [],
                "matched_total": None,
                "selected_total": None,
                "selected_total_id": selected_total_id,
                "auto_match_candidates": [],
                "difference": None,
                **scan_note,
            }
        return {
            "status": "no_source_total",
            "message": "Vision 결과에서 비교할 원본 합계를 찾지 못했습니다.",
            "amount_total": amount_total,
            "billing_amount_total": billing_amount_total,
            "basis_totals": basis_totals,
            "source_total_candidates": [],
            "matched_total": None,
            "selected_total": None,
            "selected_total_id": selected_total_id,
            "auto_match_candidates": [],
            "difference": None,
            **scan_note,
        }

    if not is_complete_scan:
        return {
            "status": "incomplete_source_scan",
            "message": (
                f"전체 {expected}개 청크 중 {processed_chunk_count}개만 Vision 결과가 있어 "
                "선택한 합계가 있더라도 최종 검산으로 확정하지 않았습니다."
            ),
            "amount_total": amount_total,
            "billing_amount_total": billing_amount_total,
            "basis_totals": basis_totals,
            "source_total_candidates": source_totals,
            "matched_total": selected_total,
            "selected_total": selected_total,
            "selected_total_id": selected_total_id,
            "auto_match_candidates": auto_matches,
            "difference": None,
            **scan_note,
        }

    if not selected_total_id:
        auto_selected = _auto_selected_match(auto_matches)
        if auto_selected:
            selected = auto_selected["candidate"]
            return {
                "status": "auto_selected_total_matched",
                "message": f"원본 합계 후보가 {auto_selected['field']}과 자동 일치했습니다.",
                "amount_total": amount_total,
                "billing_amount_total": billing_amount_total,
                "basis_totals": basis_totals,
                "source_total_candidates": source_totals,
                "matched_total": selected,
                "selected_total": selected,
                "selected_total_id": str(selected.get("id", "")),
                "matched_field": auto_selected["field"],
                "auto_match_candidates": auto_matches,
                "difference": 0,
                **scan_note,
            }
        return {
            "status": "no_user_total_selected",
            "message": "검산 기준 원본 합계를 아직 선택하지 않았습니다. 자동 일치는 참고로만 표시합니다.",
            "amount_total": amount_total,
            "billing_amount_total": billing_amount_total,
            "basis_totals": basis_totals,
            "source_total_candidates": source_totals,
            "matched_total": auto_matches[0]["candidate"] if auto_matches else None,
            "selected_total": None,
            "selected_total_id": "",
            "auto_match_candidates": auto_matches,
            "difference": None,
            **scan_note,
        }

    if not selected_total:
        return {
            "status": "no_user_total_selected",
            "message": "저장된 검산 기준 합계를 현재 Vision 후보에서 찾지 못했습니다. 다시 선택해 주세요.",
            "amount_total": amount_total,
            "billing_amount_total": billing_amount_total,
            "basis_totals": basis_totals,
            "source_total_candidates": source_totals,
            "matched_total": auto_matches[0]["candidate"] if auto_matches else None,
            "selected_total": None,
            "selected_total_id": selected_total_id,
            "auto_match_candidates": auto_matches,
            "difference": None,
            **scan_note,
        }

    selected_amount = int(selected_total["amount"])
    targets = [
        ("amount_total", amount_total),
        ("billing_amount_total", billing_amount_total),
    ] + [(str(target["field"]), int(target["amount"])) for target in basis_totals]
    for total_name, total_value in targets:
        if selected_amount == total_value:
            return {
                "status": "user_confirmed_total_matched",
                "message": f"사용자가 선택한 원본 합계가 {total_name}과 일치합니다.",
                "amount_total": amount_total,
                "billing_amount_total": billing_amount_total,
                "basis_totals": basis_totals,
                "source_total_candidates": source_totals,
                "matched_total": selected_total,
                "selected_total": selected_total,
                "selected_total_id": selected_total_id,
                "matched_field": total_name,
                "auto_match_candidates": auto_matches,
                "difference": 0,
                **scan_note,
            }

    closest_field, closest_value = min(
        targets,
        key=lambda item: abs(item[1] - selected_amount),
    )
    return {
        "status": "user_confirmed_total_mismatch",
        "message": "사용자가 선택한 원본 합계와 정규화 합계가 일치하지 않습니다.",
        "amount_total": amount_total,
        "billing_amount_total": billing_amount_total,
        "basis_totals": basis_totals,
        "source_total_candidates": source_totals,
        "matched_total": selected_total,
        "selected_total": selected_total,
        "selected_total_id": selected_total_id,
        "matched_field": closest_field,
        "auto_match_candidates": auto_matches,
        "difference": closest_value - selected_amount,
        **scan_note,
    }

def _with_validation(row: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
    copied = json.loads(json.dumps(row, ensure_ascii=False))
    copied["validation"] = {
        "needs_review": bool(issues),
        "issues": issues,
    }
    if issues:
        copied.setdefault("quality", {})
        copied["quality"]["needs_review"] = True
        existing = str(copied["quality"].get("review_reason", "")).strip()
        validation_reason = "; ".join(issue["message"] for issue in issues)
        copied["quality"]["review_reason"] = (
            f"{existing}; {validation_reason}" if existing else validation_reason
        )
    return copied


def _issue_record(row: dict[str, Any], issues: list[dict[str, str]]) -> dict[str, Any]:
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    return {
        "source": {
            "page": source.get("page"),
            "chunk_id": source.get("chunk_id"),
            "local_row_index": source.get("local_row_index"),
        },
        "transaction": row.get("transaction", {}),
        "issues": issues,
        "cells": row.get("raw", {}).get("cells", []),
        "image_ref": row.get("raw", {}).get("image_ref", ""),
    }


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "label": _issue_label(code), "message": message}


def _issue_label(code: str) -> str:
    labels = {
        "date_not_date_like": "날짜 형식",
        "amount_not_numeric": "이용금액 숫자",
        "amount_zero": "0원 거래",
        "amount_too_large": "큰 금액",
        "billing_not_numeric": "청구금액 숫자",
        "merchant_mostly_numeric": "가맹점 숫자 의심",
        "merchant_too_short": "가맹점 짧음",
        "card_label_merchant_like": "카드명/가맹점 섞임 의심",
        "row_cell_count_unstable": "열 개수 불안정",
        "date_parse_success_rate_low": "날짜 열 성공률",
        "amount_parse_success_rate_low": "금액 열 성공률",
        "merchant_numeric_like_rate_high": "가맹점 숫자 비율",
        "merchant_empty_rate_high": "가맹점 빈 값 비율",
        "card_label_column_contaminated": "카드명 열 오염 의심",
        "row_cell_count_distribution_unstable": "셀 개수 분포 불안정",
    }
    return labels.get(code, code)


def _is_date_like(value: str) -> bool:
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


def _mostly_numeric(value: str) -> bool:
    if _is_numeric_merchant_exception(value):
        return False
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return False
    digits = len(re.findall(r"\d", compact))
    letters = len(re.findall(r"[A-Za-z가-힣]", compact))
    return digits >= 3 and digits > letters


def _is_numeric_merchant_exception(value: str) -> bool:
    text = re.sub(r"\s+", "", value.strip())
    if not text:
        return False
    if "택시" in text or "하이패스" in text or "usd" in text.lower():
        return True
    if re.fullmatch(r"카페\d+", text):
        return True
    utility_tokens = ("전기", "수신료", "도시가스", "관리비", "통신료")
    return any(token in text for token in utility_tokens) and bool(re.search(r"\d", text))


def _is_hyundai_repaired_shape(cells: list[str]) -> bool:
    if len(cells) >= 9 and len(cells) > 3 and cells[1].strip() == "본인":
        card = cells[2].strip().lower()
        if card == "zero" and "포인트형" in cells[3]:
            return True
    if len(cells) >= 7 and len(cells) > 4:
        return _parse_amount(cells[4]) is not None and _parse_amount(cells[-1]) is not None
    return False


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


def _is_benefit_only_row(transaction: dict[str, Any], cells: list[str]) -> bool:
    merchant = str(transaction.get("merchant", "")).strip()
    amount = transaction.get("amount")
    if amount is not None:
        return False
    benefit_keywords = ("포인트사용", "포인트", "할인", "적립", "캐시백")
    if not any(keyword in merchant for keyword in benefit_keywords):
        return False
    return any(_parse_amount(cell) is not None for cell in cells)


def _is_foreign_billing_only_row(transaction: dict[str, Any], cells: list[str]) -> bool:
    amount = transaction.get("amount")
    billing_amount = transaction.get("billing_amount")
    if amount is not None or not isinstance(billing_amount, int):
        return False
    joined = " ".join(cells).lower()
    return "usd" in joined or "해외" in joined


def _amount_valid_or_exempt(row: dict[str, Any]) -> bool:
    transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
    cells = [str(value) for value in row.get("raw", {}).get("cells", [])]
    return (
        isinstance(transaction.get("amount"), int)
        or _is_benefit_only_row(transaction, cells)
        or _is_foreign_billing_only_row(transaction, cells)
    )


def _looks_like_merchant(value: str) -> bool:
    text = value.strip()
    if _looks_like_card_label(text):
        return False
    if len(text) >= 18 and re.search(r"[가-힣A-Za-z]", text):
        return True
    merchant_tokens = ("주식회사", "(주)", "쿠팡", "네이버", "페이", "마트", "주유", "식당")
    return any(token in text for token in merchant_tokens)


def _looks_like_card_label(value: str) -> bool:
    text = re.sub(r"\s+", " ", value.strip()).lower()
    if not text:
        return False
    card_keywords = (
        "카드",
        "본인",
        "가족",
        "법인",
        "개인",
        "zero",
        "purple",
        "red",
        "green",
        "point",
        "포인트",
    )
    return any(keyword in text for keyword in card_keywords)


def _parse_amount(value: Any) -> int | None:
    text = str(value).strip()
    if not text:
        return None
    negative = bool(re.search(r"[-−△▲]", text) or (text.startswith("(") and text.endswith(")")))
    cleaned = re.sub(r"[^\d]", "", text)
    if not cleaned:
        return None
    amount = int(cleaned)
    return -amount if negative else amount


def _total_id(label: str, amount: int, page: int, chunk_id: str) -> str:
    source = f"{page}|{chunk_id}|{label}|{amount}"
    return "total_" + sha1(source.encode("utf-8")).hexdigest()[:12]


def _selected_total_id(review_state: dict[str, Any]) -> str:
    checksum = review_state.get("checksum", {}) if isinstance(review_state.get("checksum"), dict) else {}
    return str(checksum.get("selected_total_id", "")).strip()


def _find_selected_total(
    source_totals: list[dict[str, Any]],
    selected_total_id: str,
) -> dict[str, Any] | None:
    if not selected_total_id:
        return None
    for candidate in source_totals:
        if str(candidate.get("id", "")) == selected_total_id:
            return candidate
    return None


def _auto_match_candidates(
    amount_total: int,
    billing_amount_total: int,
    rows: list[dict[str, Any]],
    source_totals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets = [
        ("amount_total", amount_total),
        ("billing_amount_total", billing_amount_total),
    ] + [
        (str(target["field"]), int(target["amount"]))
        for target in _checksum_basis_targets(rows)
        if isinstance(target.get("amount"), int)
    ]
    matches: list[dict[str, Any]] = []
    candidates = source_totals + _aggregate_total_candidates(source_totals)
    for field, total_value in targets:
        for candidate in candidates:
            if int(candidate.get("amount", 0)) == total_value:
                matches.append(
                    {
                        "field": field,
                        "candidate": candidate,
                        "difference": 0,
                        "score": _total_candidate_score(candidate),
                        "match_type": "exact",
                    }
                )
    adjustments = _checksum_adjustments(source_totals) + _transaction_discount_adjustments(rows)
    if adjustments:
        adjusted_targets = [
            ("amount_total_adjusted", amount_total + adjustments),
            ("billing_amount_total_adjusted", billing_amount_total + adjustments),
        ]
        for field, total_value in adjusted_targets:
            for candidate in candidates:
                if int(candidate.get("amount", 0)) == total_value:
                    matches.append(
                        {
                            "field": field,
                            "candidate": candidate,
                            "difference": 0,
                            "adjustment_total": adjustments,
                            "score": _total_candidate_score(candidate),
                            "match_type": "adjusted",
                        }
                    )
        for field, total_value in targets:
            if total_value <= 0:
                continue
            for candidate in candidates:
                candidate_amount = int(candidate.get("amount", 0))
                difference = candidate_amount - total_value
                if 0 < difference <= adjustments:
                    matches.append(
                        {
                            "field": f"{field}_discount_reconciled",
                            "candidate": candidate,
                            "difference": 0,
                            "adjustment_total": difference,
                            "available_adjustment_total": adjustments,
                            "score": _total_candidate_score(candidate),
                            "match_type": "discount_reconciled",
                        }
                    )
    return sorted(matches, key=lambda item: int(item.get("score", 0)), reverse=True)


def _aggregate_total_candidates(source_totals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, str] = {}
    for candidate in source_totals:
        label = str(candidate.get("label", "")).strip()
        amount = candidate.get("amount")
        if not label or not isinstance(amount, int):
            continue
        label_key = re.sub(r"\s+", "", label).lower()
        if "합계" not in label_key:
            continue
        grouped[label_key].append(candidate)
        labels.setdefault(label_key, label)

    aggregates: list[dict[str, Any]] = []
    for label_key, candidates in grouped.items():
        pages = sorted({int(candidate.get("page", 0) or 0) for candidate in candidates})
        if len(candidates) < 2 or len(pages) < 2:
            continue
        amount = sum(int(candidate["amount"]) for candidate in candidates)
        chunk_ids = [str(candidate.get("chunk_id", "")) for candidate in candidates]
        label = f"{labels[label_key]} 합산"
        aggregates.append(
            {
                "id": _aggregate_total_id(label, amount, candidates),
                "label": label,
                "value_text": f"{amount:,}",
                "amount": amount,
                "chunk_id": "+".join(chunk_ids),
                "page": pages[0],
                "pages": pages,
                "needs_review": False,
                "review_reason": "",
                "components": candidates,
            }
        )
    aggregates.extend(_samsung_usage_total_aggregates(source_totals))
    return aggregates


def _samsung_usage_total_aggregates(source_totals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_page: dict[int, dict[str, Any]] = {}
    for candidate in source_totals:
        label = re.sub(r"\s+", "", str(candidate.get("label", "")).lower())
        amount = candidate.get("amount")
        page = int(candidate.get("page", 0) or 0)
        if not page or not isinstance(amount, int):
            continue
        if "이용금액합계" not in label:
            continue
        if any(token in label for token in ("포인트", "적립", "남은금액")):
            continue
        current = by_page.get(page)
        if current is None or amount > int(current.get("amount", 0)):
            by_page[page] = candidate

    candidates = [by_page[page] for page in sorted(by_page)]
    if len(candidates) < 2:
        return []
    amount = sum(int(candidate["amount"]) for candidate in candidates)
    label = "삼성 이용금액합계 합산"
    return [
        {
            "id": _aggregate_total_id(label, amount, candidates),
            "label": label,
            "value_text": f"{amount:,}",
            "amount": amount,
            "chunk_id": "+".join(str(candidate.get("chunk_id", "")) for candidate in candidates),
            "page": int(candidates[0].get("page", 0) or 0),
            "pages": [int(candidate.get("page", 0) or 0) for candidate in candidates],
            "needs_review": False,
            "review_reason": "",
            "components": candidates,
        }
    ]


def _checksum_basis_targets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samsung_usage_total = _samsung_transaction_usage_total(rows)
    if samsung_usage_total is None:
        return []
    return [
        {
            "field": "samsung_usage_amount_total",
            "label": "삼성 거래 이용금액 합계",
            "amount": samsung_usage_total,
        }
    ]


def _samsung_transaction_usage_total(rows: list[dict[str, Any]]) -> int | None:
    total = 0
    count = 0
    for row in rows:
        if not _is_samsung_transaction_row(row):
            continue
        amount = _samsung_usage_amount(row)
        if amount is None:
            continue
        total += amount
        count += 1
    return total if count else None


def _is_samsung_transaction_row(row: dict[str, Any]) -> bool:
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    source_file = str(source.get("file", "")).lower()
    if "삼성" in source_file or "samsung" in source_file:
        return True
    cells = [str(value) for value in row.get("raw", {}).get("cells", [])]
    joined = " ".join(cells)
    return "본인 301" in joined or "삼성카드" in joined


def _samsung_usage_amount(row: dict[str, Any]) -> int | None:
    transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
    billed_amount = transaction.get("amount")
    if not isinstance(billed_amount, int):
        return None
    cells = [str(value) for value in row.get("raw", {}).get("cells", [])]
    if _is_samsung_installment_row(cells):
        return billed_amount

    extra_fields = row.get("extra_fields", {}) if isinstance(row.get("extra_fields"), dict) else {}
    extra_amount = _parse_amount(extra_fields.get("이용금액"))
    if extra_amount is not None:
        return extra_amount

    split_card_shape = len(cells) > 2 and bool(re.fullmatch(r"\d{3,4}", cells[2].strip()))
    pairs = ((4, 6), (4, 7), (4, 5)) if split_card_shape else ((3, 6), (3, 7), (3, 5), (3, 4))
    for usage_index, billed_index in pairs:
        if len(cells) <= max(usage_index, billed_index):
            continue
        if _parse_amount(cells[billed_index]) != billed_amount:
            continue
        usage_amount = _parse_amount(cells[usage_index])
        if usage_amount is not None:
            return usage_amount
    return None


def _is_samsung_installment_row(cells: list[str]) -> bool:
    return any(bool(re.fullmatch(r"\d+\s*/\s*\d+", cell.strip())) for cell in cells)


def _aggregate_total_id(label: str, amount: int, candidates: list[dict[str, Any]]) -> str:
    parts = [
        f"{candidate.get('page')}|{candidate.get('chunk_id')}|{candidate.get('label')}|{candidate.get('amount')}"
        for candidate in candidates
    ]
    source = f"aggregate|{label}|{amount}|" + "|".join(parts)
    return "total_" + sha1(source.encode("utf-8")).hexdigest()[:12]


def _auto_selected_match(auto_matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not auto_matches:
        return None
    best = auto_matches[0]
    if int(best.get("score", 0)) >= 100:
        return best
    if int(best.get("score", 0)) < 80:
        return None
    if len(auto_matches) == 1:
        return best
    second = auto_matches[1]
    if int(best.get("score", 0)) - int(second.get("score", 0)) >= 30:
        return best
    return None


def _checksum_adjustments(source_totals: list[dict[str, Any]]) -> int:
    total = 0
    for candidate in source_totals:
        label = re.sub(r"\s+", "", str(candidate.get("label", "")).lower())
        amount = candidate.get("amount")
        if not isinstance(amount, int):
            continue
        if amount < 0 and any(token in label for token in ("할인", "청구할인", "조정")):
            total += amount
    return total


def _transaction_discount_adjustments(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        extra_fields = row.get("extra_fields", {}) if isinstance(row.get("extra_fields"), dict) else {}
        for key, value in extra_fields.items():
            label = re.sub(r"\s+", "", str(key).lower())
            if not any(token in label for token in ("할인", "혜택", "discount", "point", "points")):
                continue
            amount = _parse_adjustment_amount(value)
            if isinstance(amount, int) and amount < 0:
                total += abs(amount)
    return total


def _parse_adjustment_amount(value: Any) -> int | None:
    text = str(value).strip()
    match = re.search(r"[-−△▲]\s*[\d,]+", text)
    if match:
        return _parse_amount(match.group(0))
    return _parse_amount(text)


def _total_candidate_score(candidate: dict[str, Any]) -> int:
    label = re.sub(r"\s+", "", str(candidate.get("label", "")).lower())
    if "총합계" in label or label == "합계":
        return 100
    if any(token in label for token in ("청구금액", "결제금액", "이번달")):
        return 90
    if "이용금액합계" in label:
        return 100
    if "합계" in label:
        return 80
    if "소계" in label:
        return 40
    return 20


def _is_probable_source_total(label: str, total: dict[str, Any]) -> bool:
    text = " ".join(
        str(value)
        for value in (label, total.get("context", ""), total.get("review_reason", ""))
        if value
    )
    normalized = re.sub(r"\s+", "", text).lower()
    total_keywords = (
        "합계",
        "소계",
        "총액",
        "청구금액",
        "결제금액",
        "이용금액",
        "이번달",
        "이번달결제",
        "이번달청구",
        "total",
        "sum",
        "amountdue",
        "balance",
    )
    if any(keyword in normalized for keyword in total_keywords):
        return True

    row_like_keywords = (
        "포인트사용",
        "m포인트",
        "포인트",
        "적립",
        "캐시백",
    )
    if any(keyword in normalized for keyword in row_like_keywords):
        return False
    has_date = bool(re.search(r"\b\d{1,2}[./-]\d{1,2}\b", text))
    if has_date:
        return False
    return not has_date


def _row_key(row: dict[str, Any]) -> str:
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    return "|".join(
        [
            str(source.get("page", "")),
            str(source.get("chunk_id", "")),
            str(source.get("local_row_index", "")),
        ]
    )


def _header_key(header: list[str]) -> str:
    if not header:
        return "unknown_header"
    return "|".join(re.sub(r"\s+", "", str(value).strip().lower()) for value in header)


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
