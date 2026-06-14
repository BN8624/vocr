# 검증 결과를 자동화 상태 요약으로 변환하는 유틸리티
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.normalizer import NormalizationOutput
from src.validator import ValidationOutput


def write_automation_summary(
    validation_output: ValidationOutput | None,
    normalization_output: NormalizationOutput | None,
    merged_dir: Path,
) -> Path | None:
    if not validation_output or not validation_output.validated_transactions_path.exists():
        return None

    rows = _read_jsonl(validation_output.validated_transactions_path)
    total = len(rows)
    status_counts = Counter(
        str(row.get("automation", {}).get("row_status", "blocked"))
        for row in rows
        if isinstance(row, dict)
    )
    hard_review_count = status_counts.get("needs_hard_review", 0) + status_counts.get("blocked", 0)
    manual_review_count = (
        status_counts.get("needs_light_review", 0)
        + status_counts.get("needs_hard_review", 0)
        + status_counts.get("blocked", 0)
    )
    checksum = validation_output.summary.get("checksum", {})
    checksum_status = (
        str(checksum.get("status", validation_output.checksum_status))
        if isinstance(checksum, dict)
        else validation_output.checksum_status
    )
    checksum_review_required = checksum_status in {
        "no_user_total_selected",
        "incomplete_source_scan",
        "user_confirmed_total_mismatch",
    }
    blocked_reasons = _blocked_reasons(validation_output, checksum_status)
    blocked_count = total if blocked_reasons else 0
    summary = {
        "schema_version": "1.0",
        "transaction_count": total,
        "auto_accept_count": status_counts.get("auto_confirmed", 0)
        + status_counts.get("auto_confirmed_with_warning", 0),
        "manual_review_count": manual_review_count,
        "hard_review_count": hard_review_count,
        "blocked_count": blocked_count,
        "auto_accept_rate": _rate(
            status_counts.get("auto_confirmed", 0)
            + status_counts.get("auto_confirmed_with_warning", 0),
            total,
        ),
        "manual_review_rate": _rate(manual_review_count, total),
        "hard_review_rate": _rate(hard_review_count, total),
        "blocked_rate": _rate(blocked_count, total),
        "row_status_counts": dict(status_counts),
        "checksum": {
            "status": checksum_status,
            "source": "auto_selected" if checksum_status == "auto_selected_total_matched" else "not_auto_selected",
            "difference": validation_output.checksum_difference,
            "review_required": checksum_review_required,
        },
        "checksum_review_required": checksum_review_required,
        "normalization_review_count": normalization_output.review_count if normalization_output else 0,
        "validation_issue_row_count": validation_output.issue_row_count,
        "blocked_reasons": blocked_reasons,
    }
    path = merged_dir / "automation_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _blocked_reasons(validation_output: ValidationOutput, checksum_status: str) -> list[str]:
    reasons = []
    if checksum_status in {"incomplete_source_scan", "user_confirmed_total_mismatch"}:
        reasons.append(checksum_status)
    if validation_output.issue_row_count:
        reasons.append("validation_issues")
    return reasons


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
