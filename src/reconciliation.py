# 현대카드 등 복합 명세서의 섹션별 검산 리포트를 생성한다.
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.validator import ValidationOutput


def write_section_reconciliation(validation_output: ValidationOutput | None, merged_dir: Path) -> Path | None:
    if not validation_output or not validation_output.validated_transactions_path.exists():
        return None

    rows = _read_jsonl(validation_output.validated_transactions_path)
    checksum = validation_output.summary.get("checksum", {})
    source_totals = []
    if isinstance(checksum, dict):
        source_totals = [
            item for item in checksum.get("source_total_candidates", []) if isinstance(item, dict)
        ]

    page_pairs = _page_pairs(rows, source_totals)
    pair_reports = [_pair_report(pair, rows, source_totals) for pair in page_pairs]
    summary = {
        "schema_version": "1.0",
        "status": _overall_status(pair_reports),
        "issuer_hint": _issuer_hint(rows),
        "strategy": "section_aware_reconciliation_probe",
        "pair_count": len(pair_reports),
        "pairs": pair_reports,
    }
    path = merged_dir / "section_reconciliation.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_section_reconciliation(merged_dir: Path) -> dict[str, Any] | None:
    path = merged_dir / "section_reconciliation.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _pair_report(pair: tuple[int, int], rows: list[dict[str, Any]], source_totals: list[dict[str, Any]]) -> dict[str, Any]:
    start, end = pair
    pair_rows = [row for row in rows if start <= _page(row) <= end]
    section_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"row_count": 0, "amount_total": 0, "billing_amount_total": 0})
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        section = _section_type(row)
        amount = _amount(row, "amount")
        billing = _amount(row, "billing_amount")
        section_totals[section]["row_count"] += 1
        section_totals[section]["amount_total"] += amount
        section_totals[section]["billing_amount_total"] += billing
        if len(samples[section]) < 3:
            samples[section].append(_sample(row))

    source_candidates = [
        total for total in source_totals if start <= int(total.get("page", 0) or 0) <= end
    ]
    source_total = _best_pair_total(source_candidates)
    amount_total = sum(_amount(row, "amount") for row in pair_rows)
    billing_total = sum(_amount(row, "billing_amount") for row in pair_rows)
    explanation = _difference_explanation(
        source_total=source_total,
        amount_total=amount_total,
        section_totals=section_totals,
    )
    return {
        "pages": [start, end],
        "row_count": len(pair_rows),
        "source_total": source_total,
        "amount_total": amount_total,
        "billing_amount_total": billing_total,
        "difference": None if source_total is None else amount_total - int(source_total.get("amount", 0)),
        "section_totals": dict(sorted(section_totals.items())),
        "section_samples": dict(samples),
        "source_candidates": source_candidates,
        "explanation": explanation,
    }


def _difference_explanation(
    source_total: dict[str, Any] | None,
    amount_total: int,
    section_totals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if source_total is None:
        return {"status": "no_pair_total", "message": "이 페이지 묶음의 원본 총합계 후보가 없습니다."}
    difference = amount_total - int(source_total.get("amount", 0))
    if difference == 0:
        return {"status": "matched", "message": "거래 이용금액 합계가 원본 총합계와 일치합니다."}

    candidates = []
    for section, totals in section_totals.items():
        amount = int(totals.get("amount_total", 0) or 0)
        billing = int(totals.get("billing_amount_total", 0) or 0)
        if amount and amount == difference:
            candidates.append({"section": section, "field": "amount_total", "amount": amount})
        if billing and billing == difference:
            candidates.append({"section": section, "field": "billing_amount_total", "amount": billing})
        if amount and -amount == difference:
            candidates.append({"section": section, "field": "amount_total_negated", "amount": amount})
        if billing and -billing == difference:
            candidates.append({"section": section, "field": "billing_amount_total_negated", "amount": billing})
    if candidates:
        return {
            "status": "candidate_section_match",
            "message": "차이와 같은 섹션 합계 후보가 있습니다. 자동 적용 전 표본 검증이 필요합니다.",
            "candidates": candidates,
        }
    return {
        "status": "unexplained",
        "message": "현재 섹션 합계만으로 차이를 안전하게 설명할 수 없습니다.",
        "needed_adjustment": -difference,
    }


def _best_pair_total(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    totals = [
        item for item in candidates
        if "총" in re.sub(r"\s+", "", str(item.get("label", ""))) and isinstance(item.get("amount"), int)
    ]
    if totals:
        return max(totals, key=lambda item: _total_score(item))
    subtotals = [
        item for item in candidates
        if "일부결제금액이월약정소계" in re.sub(r"\s+", "", str(item.get("label", ""))) and isinstance(item.get("amount"), int)
    ]
    if subtotals:
        return max(subtotals, key=lambda item: _total_score(item))
    return None


def _total_score(candidate: dict[str, Any]) -> tuple[int, int]:
    label = re.sub(r"\s+", "", str(candidate.get("label", "")))
    score = 0
    if "총합계" in label or label == "총합계":
        score += 100
    elif "총" in label and "합계" in label:
        score += 90
    elif "소계" in label:
        score += 60
    return (score, abs(int(candidate.get("amount", 0) or 0)))


def _section_type(row: dict[str, Any]) -> str:
    header = _joined(row.get("raw", {}).get("header", []))
    cells = _joined(row.get("raw", {}).get("cells", []))
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    chunk_id = str(source.get("chunk_id", ""))
    if "국가" in header and "해외이용금액" in header:
        return "foreign_detail"
    if any(token in header + " " + cells for token in ("포인트", "캐시백", "마일리지", "바우처")):
        if _amount(row, "amount") == 0 and _amount(row, "billing_amount") == 0:
            return "benefit_detail"
    if "정기결제" in header or "정기결제" in cells:
        return "subscription_detail"
    if "취소매출" in header or "취소매출" in cells:
        return "cancellation_detail"
    if "_totals_" in chunk_id:
        return "total_detail"
    return "billing_detail"


def _page_pairs(rows: list[dict[str, Any]], source_totals: list[dict[str, Any]]) -> list[tuple[int, int]]:
    pages = {_page(row) for row in rows if _page(row)}
    pages.update(int(total.get("page", 0) or 0) for total in source_totals)
    pairs = set()
    for page in pages:
        if page <= 0:
            continue
        start = page if page % 2 == 1 else page - 1
        pairs.add((start, start + 1))
    return sorted(pairs)


def _issuer_hint(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
        name = str(source.get("file", "")).lower()
        if "현대" in name or "hyundai" in name:
            return "hyundai"
    return "unknown"


def _overall_status(pair_reports: list[dict[str, Any]]) -> str:
    if not pair_reports:
        return "not_available"
    statuses = {
        str(pair.get("explanation", {}).get("status", ""))
        for pair in pair_reports
    }
    if statuses == {"matched"}:
        return "matched"
    if "candidate_section_match" in statuses:
        return "needs_profile_rule"
    return "needs_investigation"


def _sample(row: dict[str, Any]) -> dict[str, Any]:
    transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    return {
        "page": source.get("page"),
        "chunk_id": source.get("chunk_id"),
        "date": transaction.get("date"),
        "merchant": transaction.get("merchant"),
        "amount": transaction.get("amount"),
        "billing_amount": transaction.get("billing_amount"),
    }


def _amount(row: dict[str, Any], field: str) -> int:
    transaction = row.get("transaction", {}) if isinstance(row.get("transaction"), dict) else {}
    value = transaction.get(field)
    return value if isinstance(value, int) else 0


def _page(row: dict[str, Any]) -> int:
    source = row.get("source", {}) if isinstance(row.get("source"), dict) else {}
    return int(source.get("page", 0) or 0)


def _joined(values: Any) -> str:
    if not isinstance(values, list):
        return str(values)
    return " ".join(str(value) for value in values)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
