from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.row_merger import RowMergeOutput


MAPPING_OPTIONS = [
    "date",
    "card_label",
    "merchant",
    "amount",
    "billing_amount",
    "transaction_type",
    "discount",
    "points",
    "installment_month",
    "installment_round",
    "fee",
    "foreign_amount",
    "currency",
    "exchange_rate",
    "memo",
    "extra",
    "ignore",
]

CORE_FIELDS = {"date", "card_label", "merchant", "amount", "billing_amount"}
REQUIRED_FIELDS = {"date", "merchant", "amount"}


@dataclass(frozen=True)
class MappingOutput:
    suggestions_path: Path
    profile_dir: Path
    table_groups: list[dict[str, Any]]
    option_labels: dict[str, str]


def build_mapping_suggestions(
    merge_output: RowMergeOutput | None,
    output_dir: Path,
    profiles_dir: Path,
) -> MappingOutput | None:
    if not merge_output or not merge_output.rows_merged_path.exists():
        return None

    profiles_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_jsonl(merge_output.rows_merged_path)
    groups = _group_rows_by_header(rows)
    table_groups = [_build_table_group(group_id, rows) for group_id, rows in groups.items()]

    payload = {
        "schema_version": "1.0",
        "status": "suggested",
        "profile_dir": str(profiles_dir),
        "option_labels": _option_labels(),
        "table_groups": table_groups,
    }
    suggestions_path = output_dir / "merged" / "mapping_suggestions.json"
    suggestions_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return MappingOutput(
        suggestions_path=suggestions_path,
        profile_dir=profiles_dir,
        table_groups=table_groups,
        option_labels=payload["option_labels"],
    )


def load_mapping_suggestions(output_dir: Path, profiles_dir: Path) -> MappingOutput | None:
    suggestions_path = output_dir / "merged" / "mapping_suggestions.json"
    if not suggestions_path.exists():
        return None
    payload = json.loads(suggestions_path.read_text(encoding="utf-8"))
    return MappingOutput(
        suggestions_path=suggestions_path,
        profile_dir=profiles_dir,
        table_groups=list(payload.get("table_groups", [])),
        option_labels=dict(payload.get("option_labels", _option_labels())),
    )


def _group_rows_by_header(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        header = [str(value) for value in row.get("raw", {}).get("header", [])]
        key = _header_key(header)
        groups[key].append(row)
    return dict(groups)


def _build_table_group(group_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    header = [str(value) for value in rows[0].get("raw", {}).get("header", [])]
    max_cells = max([len(header)] + [len(row.get("raw", {}).get("cells", [])) for row in rows])
    labels = header + [f"col_{index}" for index in range(len(header) + 1, max_cells + 1)]

    columns = []
    for index, label in enumerate(labels):
        values = _sample_column_values(rows, index)
        suggestion = _suggest_field(label, values)
        columns.append(
            {
                "column_index": index,
                "column_id": f"col_{index + 1}",
                "header": label,
                "sample_values": values[:6],
                "suggested_field": suggestion["field"],
                "confidence": suggestion["confidence"],
                "reason": suggestion["reason"],
                "position": _column_position(index, labels),
                "source_image_refs": _source_image_refs(rows),
                "requires_review": False,
                "review_reason": "",
            }
        )

    _mark_review_columns(columns)

    return {
        "group_id": group_id,
        "row_count": len(rows),
        "header": header,
        "columns": columns,
        "review_column_count": sum(1 for column in columns if column["requires_review"]),
        "auto_column_count": sum(1 for column in columns if not column["requires_review"]),
    }


def _mark_review_columns(columns: list[dict[str, Any]]) -> None:
    field_counts: dict[str, int] = defaultdict(int)
    for column in columns:
        field = str(column["suggested_field"])
        if field not in {"extra", "ignore"}:
            field_counts[field] += 1

    suggested_fields = {str(column["suggested_field"]) for column in columns}
    missing_required = REQUIRED_FIELDS - suggested_fields

    for column in columns:
        field = str(column["suggested_field"])
        confidence = str(column["confidence"])
        reasons: list[str] = []

        if field in CORE_FIELDS and confidence != "high":
            reasons.append("핵심 열인데 자동 판단 신뢰도가 높지 않습니다.")
        if field_counts.get(field, 0) > 1 and field in CORE_FIELDS:
            reasons.append(f"{field} 후보가 여러 개입니다.")
        if field == "extra" and confidence == "low" and _has_many_values(column):
            reasons.append("추가필드 후보입니다. 필요한 열인지 한 번만 확인하세요.")

        column["requires_review"] = bool(reasons)
        column["review_reason"] = " ".join(reasons)

    if missing_required:
        for column in columns:
            if column["requires_review"]:
                continue
            if str(column["suggested_field"]) in {"extra", "ignore"} and _has_many_values(column):
                column["requires_review"] = True
                missing = ", ".join(sorted(missing_required))
                column["review_reason"] = f"필수 필드({missing}) 후보가 부족해서 확인이 필요합니다."
                break


def _has_many_values(column: dict[str, Any]) -> bool:
    return len([value for value in column.get("sample_values", []) if str(value).strip()]) >= 2


def _suggest_field(header: str, values: list[str]) -> dict[str, str]:
    text = _norm(header)
    nonempty = [value for value in values if value.strip()]

    if any(token in text for token in ("이용일", "승인일", "일자", "date")):
        return _suggest("date", "high", "헤더가 날짜 열처럼 보입니다.")
    if any(token in text for token in ("카드", "card")):
        return _suggest("card_label", "high", "헤더가 카드명/카드번호 열처럼 보입니다.")
    if any(token in text for token in ("가맹점", "merchant", "사용처")):
        return _suggest("merchant", "high", "헤더가 가맹점 열처럼 보입니다.")
    if any(token in text for token in ("수수료", "이자", "fee")):
        return _suggest("fee", "medium", "헤더가 수수료 열처럼 보입니다.")
    if any(token in text for token in ("할인금액", "혜택금액", "할인", "혜택액")):
        return _suggest("discount", "medium", "헤더가 할인/혜택 금액 열처럼 보입니다.")
    if "혜택" in text:
        return _suggest("memo", "medium", "헤더가 혜택 설명 열처럼 보입니다.")
    if any(token in text for token in ("이용금액", "사용금액", "승인금액", "amount")):
        return _suggest("amount", "high", "헤더가 이용금액 열처럼 보입니다.")
    if any(token in text for token in ("결제원금", "청구금액", "입금하실금액", "billing")):
        return _suggest("billing_amount", "high", "헤더가 결제/청구 금액 열처럼 보입니다.")
    if any(token in text for token in ("일시불", "할부", "이용구분", "거래구분")):
        return _suggest("transaction_type", "medium", "헤더가 거래 유형 열처럼 보입니다.")

    if nonempty:
        date_rate = sum(1 for value in nonempty if _is_date_like(value)) / len(nonempty)
        money_rate = sum(1 for value in nonempty if _is_money_like(value)) / len(nonempty)
        long_text_rate = sum(1 for value in nonempty if len(value.strip()) >= 4 and not _is_money_like(value)) / len(nonempty)
        if date_rate >= 0.7:
            return _suggest("date", "medium", "값 패턴이 날짜처럼 보입니다.")
        if money_rate >= 0.8:
            return _suggest("amount", "low", "값 대부분이 금액처럼 보입니다. 실제 의미는 확인이 필요합니다.")
        if long_text_rate >= 0.7:
            return _suggest("merchant", "low", "값이 텍스트 중심이라 가맹점 후보로 보입니다.")

    return _suggest("extra", "low", "자동 판단이 어려워 추가필드로 제안합니다.")


def _sample_column_values(rows: list[dict[str, Any]], column_index: int) -> list[str]:
    samples: list[str] = []
    seen: set[str] = set()
    for row in rows:
        cells = [str(value) for value in row.get("raw", {}).get("cells", [])]
        if column_index >= len(cells):
            continue
        value = cells[column_index].strip()
        if not value or value in seen:
            continue
        samples.append(value)
        seen.add(value)
        if len(samples) >= 8:
            break
    return samples


def _column_position(column_index: int, labels: list[str]) -> dict[str, Any]:
    total = max(1, len(labels))
    left = labels[column_index - 1] if column_index > 0 else ""
    right = labels[column_index + 1] if column_index + 1 < len(labels) else ""
    start_percent = round((column_index / total) * 100, 1)
    end_percent = round(((column_index + 1) / total) * 100, 1)
    center_percent = round(((column_index + 0.5) / total) * 100, 1)
    return {
        "index": column_index + 1,
        "total": total,
        "left_header": left,
        "right_header": right,
        "start_percent": start_percent,
        "end_percent": end_percent,
        "center_percent": center_percent,
    }


def _source_image_refs(rows: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for row in rows:
        image_ref = str(row.get("raw", {}).get("image_ref", "")).strip()
        if not image_ref or image_ref in seen:
            continue
        refs.append(image_ref)
        seen.add(image_ref)
        if len(refs) >= 3:
            break
    return refs


def _header_key(header: list[str]) -> str:
    if not header:
        return "unknown_header"
    return "|".join(_norm(value) for value in header)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value).strip().lower())


def _is_date_like(value: str) -> bool:
    value = value.strip()
    return bool(re.fullmatch(r"\d{1,2}[./-]\d{1,2}", value) or re.fullmatch(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", value))


def _is_money_like(value: str) -> bool:
    value = value.strip().replace(",", "")
    return bool(re.fullmatch(r"-?\d+", value))


def _suggest(field: str, confidence: str, reason: str) -> dict[str, str]:
    return {"field": field, "confidence": confidence, "reason": reason}


def _option_labels() -> dict[str, str]:
    return {
        "date": "이용일",
        "card_label": "이용카드",
        "merchant": "가맹점",
        "amount": "이용금액",
        "billing_amount": "결제/청구금액",
        "transaction_type": "거래유형",
        "discount": "할인",
        "points": "포인트",
        "installment_month": "할부개월",
        "installment_round": "할부회차",
        "fee": "수수료",
        "foreign_amount": "해외금액",
        "currency": "통화",
        "exchange_rate": "환율",
        "memo": "메모",
        "extra": "추가필드",
        "ignore": "무시",
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
