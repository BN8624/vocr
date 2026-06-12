from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
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
) -> ValidationOutput | None:
    if not normalization_output or not normalization_output.transactions_path.exists():
        return None

    merged_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_jsonl(normalization_output.transactions_path)
    source_totals = _source_total_candidates(vision_results or [])
    row_issues = _validate_rows(rows)
    checksum = _checksum_summary(
        amount_total=normalization_output.amount_total,
        billing_amount_total=normalization_output.billing_amount_total,
        source_totals=source_totals,
        processed_chunk_count=len(vision_results or []),
        expected_chunk_count=expected_chunk_count,
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
                "issues": issue_records,
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
        if expected_count is not None and len(cells) != expected_count:
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
            key = (label, amount)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "label": label,
                    "amount": amount,
                    "chunk_id": result.chunk_id,
                    "page": result.page_number,
                }
            )
    return candidates


def _checksum_summary(
    amount_total: int,
    billing_amount_total: int,
    source_totals: list[dict[str, Any]],
    processed_chunk_count: int,
    expected_chunk_count: int | None,
) -> dict[str, Any]:
    expected = expected_chunk_count or processed_chunk_count
    is_complete_scan = expected <= 0 or processed_chunk_count >= expected
    scan_note = {
        "processed_chunk_count": processed_chunk_count,
        "expected_chunk_count": expected,
        "is_complete_scan": is_complete_scan,
    }

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
                "source_total_candidates": [],
                "matched_total": None,
                "difference": None,
                **scan_note,
            }
        return {
            "status": "no_source_total",
            "message": "Vision 결과에서 비교할 원본 합계를 찾지 못했습니다.",
            "amount_total": amount_total,
            "billing_amount_total": billing_amount_total,
            "source_total_candidates": [],
            "matched_total": None,
            "difference": None,
            **scan_note,
        }

    targets = [
        ("amount_total", amount_total),
        ("billing_amount_total", billing_amount_total),
    ]
    for total_name, total_value in targets:
        for candidate in source_totals:
            if int(candidate["amount"]) == total_value:
                return {
                    "status": "matched",
                    "message": f"{total_name}이 원본 합계 후보와 일치합니다.",
                    "amount_total": amount_total,
                    "billing_amount_total": billing_amount_total,
                    "source_total_candidates": source_totals,
                    "matched_total": candidate,
                    "matched_field": total_name,
                    "difference": 0,
                    **scan_note,
                }

    if not is_complete_scan:
        return {
            "status": "incomplete_source_scan",
            "message": (
                f"원본 합계 후보는 찾았지만 전체 {expected}개 청크 중 {processed_chunk_count}개만 "
                "Vision 결과가 있어 최종 검산으로 확정하지 않았습니다."
            ),
            "amount_total": amount_total,
            "billing_amount_total": billing_amount_total,
            "source_total_candidates": source_totals,
            "matched_total": None,
            "difference": None,
            **scan_note,
        }

    closest = min(
        (
            {
                "candidate": candidate,
                "field": field,
                "difference": total_value - int(candidate["amount"]),
                "abs_difference": abs(total_value - int(candidate["amount"])),
            }
            for field, total_value in targets
            for candidate in source_totals
        ),
        key=lambda item: item["abs_difference"],
    )
    return {
        "status": "mismatch",
        "message": "정규화 합계가 원본 합계 후보와 일치하지 않습니다.",
        "amount_total": amount_total,
        "billing_amount_total": billing_amount_total,
        "source_total_candidates": source_totals,
        "matched_total": closest["candidate"],
        "matched_field": closest["field"],
        "difference": closest["difference"],
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
    }
    return labels.get(code, code)


def _is_date_like(value: str) -> bool:
    text = value.strip()
    return bool(
        re.fullmatch(r"\d{1,2}[./-]\d{1,2}", text)
        or re.fullmatch(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", text)
    )


def _mostly_numeric(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return False
    digits = len(re.findall(r"\d", compact))
    letters = len(re.findall(r"[A-Za-z가-힣]", compact))
    return digits >= 3 and digits > letters


def _looks_like_merchant(value: str) -> bool:
    text = value.strip()
    if len(text) >= 18 and re.search(r"[가-힣A-Za-z]", text):
        return True
    merchant_tokens = ("주식회사", "(주)", "쿠팡", "네이버", "페이", "마트", "주유", "식당")
    return any(token in text for token in merchant_tokens)


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
