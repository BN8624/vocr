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
    applied_profiles: list[str]


def build_mapping_suggestions(
    merge_output: RowMergeOutput | None,
    output_dir: Path,
    profiles_dir: Path,
    profile_paths: list[Path] | None = None,
) -> MappingOutput | None:
    if not merge_output or not merge_output.rows_merged_path.exists():
        return None

    profiles_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_jsonl(merge_output.rows_merged_path)
    groups = _group_rows_by_header(rows)
    table_groups = [_build_table_group(group_id, rows) for group_id, rows in groups.items()]
    applied_profiles = _apply_saved_profiles(table_groups, profiles_dir, profile_paths or [])

    payload = {
        "schema_version": "1.0",
        "status": "profile_applied" if applied_profiles else "suggested",
        "profile_dir": str(profiles_dir),
        "applied_profiles": applied_profiles,
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
        applied_profiles=applied_profiles,
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
        applied_profiles=[str(value) for value in payload.get("applied_profiles", [])],
    )


def _apply_saved_profiles(
    table_groups: list[dict[str, Any]],
    profiles_dir: Path,
    explicit_paths: list[Path],
) -> list[str]:
    profiles = _load_profiles(profiles_dir, explicit_paths)
    if not profiles:
        return []

    applied: list[str] = []
    for group in table_groups:
        match = _matching_profile(group, profiles)
        if not match:
            continue
        profile = match["profile"]
        profile_group = match["profile_group"]
        profile_name = str(profile["path"])
        selected_by_column = _profile_columns_by_id(profile_group, group)
        if not selected_by_column:
            continue
        group["profile_match"] = {
            "status": match["status"],
            "score": match["score"],
            "profile_source": profile_name,
            "reason": match["reason"],
        }
        if match["status"] == "candidate":
            group["profile_candidate"] = profile_name
            group["profile_match"]["selected_columns"] = selected_by_column
            continue
        for column in group.get("columns", []):
            if not isinstance(column, dict):
                continue
            selected = selected_by_column.get(str(column.get("column_id", "")))
            if selected not in MAPPING_OPTIONS:
                continue
            column["selected_field"] = selected
            column["suggested_field"] = selected
            column["confidence"] = "profile"
            column["reason"] = f"저장된 매핑 프로필 적용: {Path(profile_name).name} ({match['score']:.2f})"
            column["requires_review"] = False
            column["review_reason"] = ""
            column["profile_source"] = profile_name
        group["review_column_count"] = sum(
            1 for column in group.get("columns", []) if isinstance(column, dict) and column.get("requires_review")
        )
        group["auto_column_count"] = sum(
            1 for column in group.get("columns", []) if isinstance(column, dict) and not column.get("requires_review")
        )
        group["profile_source"] = profile_name
        if profile_name not in applied:
            applied.append(profile_name)
    return applied


def _load_profiles(profiles_dir: Path, explicit_paths: list[Path]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    if profiles_dir.exists():
        paths.extend(sorted(path for path in profiles_dir.glob("*.json") if path.is_file()))
    paths.extend(explicit_paths)

    profiles: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            profiles.append({"path": str(resolved), "payload": payload})
    return profiles


def _matching_profile(
    group: dict[str, Any],
    profiles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    group_id = str(group.get("group_id", ""))
    header_key = _header_key([str(value) for value in group.get("header", [])])
    group_signature = _table_signature(group)
    best_match: dict[str, Any] | None = None
    for profile in profiles:
        payload = profile["payload"]
        for profile_group in payload.get("table_groups", []):
            if not isinstance(profile_group, dict):
                continue
            profile_group_id = str(profile_group.get("group_id", ""))
            profile_header_key = _header_key([str(value) for value in profile_group.get("header", [])])
            if profile_group_id in {group_id, header_key} or profile_header_key == header_key:
                return {
                    "profile": profile,
                    "profile_group": profile_group,
                    "score": 1.0,
                    "status": "auto",
                    "reason": "header_or_group_exact_match",
                }
            score = _signature_similarity(group_signature, _table_signature(profile_group))
            if best_match is None or score > float(best_match["score"]):
                best_match = {
                    "profile": profile,
                    "profile_group": profile_group,
                    "score": score,
                    "status": "auto" if score >= 0.95 else "candidate" if score >= 0.80 else "none",
                    "reason": "table_signature_similarity",
                }
    if best_match and best_match["status"] in {"auto", "candidate"}:
        return best_match
    return None


def _profile_columns_by_id(
    profile_group: dict[str, Any],
    group: dict[str, Any],
) -> dict[str, str]:
    profile_columns = [column for column in profile_group.get("columns", []) if isinstance(column, dict)]
    group_columns = [column for column in group.get("columns", []) if isinstance(column, dict)]
    selected: dict[str, str] = {}

    by_id: dict[str, str] = {}
    for column in profile_columns:
        column_id = str(column.get("column_id", ""))
        field = str(column.get("selected_field") or column.get("suggested_field") or "")
        if column_id and field:
            by_id[column_id] = field

    for column in group_columns:
        column_id = str(column.get("column_id", ""))
        if column_id in by_id:
            selected[column_id] = by_id[column_id]

    if selected:
        return selected

    for index, column in enumerate(group_columns):
        if index >= len(profile_columns):
            continue
        field = str(
            profile_columns[index].get("selected_field")
            or profile_columns[index].get("suggested_field")
            or ""
        )
        if not field:
            continue
        selected[str(column.get("column_id", f"col_{index + 1}"))] = field
    return selected


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

    _repair_shifted_card_statement_columns(columns)
    _repair_hyundai_point_statement_columns(columns)
    _repair_kb_bizcard_statement_columns(columns)
    _repair_kb_bizcard_shifted_columns(columns)
    _repair_installment_statement_columns(columns)
    _repair_woori_payable_statement_columns(columns)
    _repair_nh_principal_statement_columns(columns)
    _repair_samsung_billing_statement_columns(columns)
    _mark_review_columns(columns)

    group = {
        "group_id": group_id,
        "row_count": len(rows),
        "header": header,
        "columns": columns,
        "review_column_count": sum(1 for column in columns if column["requires_review"]),
        "auto_column_count": sum(1 for column in columns if not column["requires_review"]),
    }
    group["table_signature"] = _table_signature(group)
    return group


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


def _repair_shifted_card_statement_columns(columns: list[dict[str, Any]]) -> None:
    if len(columns) < 7:
        return
    headers = [_norm(str(column.get("header", ""))) for column in columns]
    if _has_stable_statement_headers(headers):
        return
    if _sample_rate(columns[0], _is_date_like) < 0.7:
        return

    card_index = _card_label_index(columns)
    if card_index is None:
        return
    merchant_index = card_index + 1
    amount_index = card_index + 2
    rate_index = card_index + 3
    points_index = card_index + 4
    billing_index = card_index + 5
    if billing_index >= len(columns):
        return
    if _sample_rate(columns[merchant_index], _is_text_like_not_money) < 0.6:
        return
    if _sample_rate(columns[amount_index], _is_money_like) < 0.6:
        return
    if _sample_rate(columns[billing_index], _is_money_like) < 0.6:
        return

    repairs = {
        0: ("date", "high", "값 패턴이 날짜 열로 안정적입니다."),
        card_index: ("card_label", "high", "값 패턴이 카드명 열로 안정적입니다."),
        merchant_index: ("merchant", "high", "카드명 다음의 긴 텍스트 열이라 가맹점으로 보정합니다."),
        amount_index: ("amount", "high", "가맹점 다음의 금액 열이라 이용금액으로 보정합니다."),
        rate_index: ("discount", "medium", "금액 다음의 비율 열이라 혜택 비율로 보정합니다."),
        points_index: ("points", "medium", "비율 다음의 작은 숫자 열이라 포인트로 보정합니다."),
        billing_index: ("billing_amount", "high", "마지막 금액 열이라 청구/결제 금액으로 보정합니다."),
    }
    for index, (field, confidence, reason) in repairs.items():
        columns[index]["suggested_field"] = field
        columns[index]["confidence"] = confidence
        columns[index]["reason"] = reason


def _repair_installment_statement_columns(columns: list[dict[str, Any]]) -> None:
    headers = [_norm(str(column.get("header", ""))) for column in columns]
    joined = "|".join(headers)
    if "할부" not in joined or "이용금액" not in joined:
        return

    principal_indexes = [
        index
        for index, header in enumerate(headers)
        if "원금" in header and "결제후" not in header and "잔액" not in header
    ]
    if not principal_indexes:
        return

    for index, header in enumerate(headers):
        if "이용금액" in header:
            _set_column_role(
                columns[index],
                "extra",
                "medium",
                "할부 청구 표에서는 원거래 이용금액을 보조 원본 필드로 남깁니다.",
            )
        elif index in principal_indexes:
            _set_column_role(
                columns[index],
                "amount",
                "high",
                "할부 청구 표의 이번 달 원금 열을 검산 기준 이용금액으로 보정합니다.",
            )
        elif "잔액" in header:
            _set_column_role(
                columns[index],
                "extra",
                "medium",
                "결제 후 잔액은 검산 합계에서 제외되는 보조 원본 필드입니다.",
            )
        elif header == "금액" and index > 0 and "구분" in headers[index - 1]:
            _set_column_role(
                columns[index],
                "discount",
                "medium",
                "혜택 구분 다음의 금액 열을 혜택/할인 금액으로 보정합니다.",
            )


def _repair_woori_payable_statement_columns(columns: list[dict[str, Any]]) -> None:
    if len(columns) != 7:
        return
    if _sample_rate(columns[0], _is_date_like) < 0.8:
        return
    if _sample_rate(columns[1], _is_text_like_not_money) < 0.8:
        return
    money_indexes = [2, 3, 5, 6]
    if any(_sample_rate(columns[index], _is_money_like) < 0.8 for index in money_indexes):
        return
    if _sample_rate(columns[4], _is_text_like_not_money) < 0.8:
        return
    if _sample_rate(columns[2], _same_value_as(columns[3])) < 0.8:
        return
    if not _has_discounted_payable_pattern(columns[2], columns[5], columns[6]):
        return

    roles = [
        ("date", "high", "Woori statement date column."),
        ("merchant", "high", "Woori statement merchant column."),
        ("amount", "high", "Woori statement original use amount column."),
        ("extra", "medium", "Woori statement intermediate billing display column kept as source detail."),
        ("memo", "medium", "Woori statement benefit label column."),
        ("discount", "medium", "Woori statement benefit amount column."),
        ("billing_amount", "high", "Woori statement final payable amount column."),
    ]
    for column, (field, confidence, reason) in zip(columns, roles):
        _set_column_role(column, field, confidence, reason)


def _repair_nh_principal_statement_columns(columns: list[dict[str, Any]]) -> None:
    if len(columns) != 8:
        return
    if _sample_rate(columns[0], _is_date_like) < 0.8:
        return
    if _sample_rate(columns[1], _is_text_like_not_money) < 0.8:
        return
    if _sample_rate(columns[2], _is_money_like) < 0.8:
        return
    if _sample_rate(columns[3], _is_benefit_value_like) < 0.6:
        return
    if _sample_rate(columns[4], _is_installment_round_like) < 0.5:
        return
    if _sample_rate(columns[5], _is_money_like) < 0.8:
        return
    if _sample_rate(columns[6], _is_money_like) < 0.8:
        return
    if _sample_rate(columns[7], _is_money_like) < 0.5:
        return

    roles = [
        ("date", "high", "NH statement date column."),
        ("merchant", "high", "NH statement merchant column."),
        ("extra", "medium", "NH statement original use amount kept as source detail."),
        ("discount", "medium", "NH statement benefit amount column."),
        ("extra", "medium", "NH statement installment round column."),
        ("amount", "high", "NH statement principal column used for checksum."),
        ("fee", "medium", "NH statement fee column."),
        ("extra", "medium", "NH statement remaining balance column excluded from checksum."),
    ]
    for column, (field, confidence, reason) in zip(columns, roles):
        _set_column_role(column, field, confidence, reason)


def _repair_hyundai_point_statement_columns(columns: list[dict[str, Any]]) -> None:
    headers = [_norm(str(column.get("header", ""))) for column in columns]
    joined = "|".join(headers)
    if "이용금액" not in joined or not any("적립" in header for header in headers):
        return

    for index, header in enumerate(headers):
        if header in {"일자", "날짜", "이용일"}:
            _set_column_role(columns[index], "date", "high", "현대카드 포인트형 표의 날짜 열로 보정합니다.")
        elif header in {"카드명", "이용카드"}:
            _set_column_role(columns[index], "card_label", "high", "현대카드 포인트형 표의 카드명 열로 보정합니다.")
        elif header in {"가맹점명", "이용가맹점"}:
            _set_column_role(columns[index], "merchant", "high", "현대카드 포인트형 표의 가맹점 열로 보정합니다.")
        elif header == "이용금액":
            _set_column_role(columns[index], "amount", "high", "현대카드 포인트형 표의 이용금액 열로 보정합니다.")
        elif "청구금액" in header:
            _set_column_role(columns[index], "billing_amount", "high", "현대카드 포인트형 표의 청구금액 열로 보정합니다.")
        elif "적립률" in header or "적립율" in header:
            _set_column_role(columns[index], "extra", "medium", "포인트 적립률은 검산 핵심 금액에서 제외합니다.")
        elif "적립포인트" in header or "적립예정" in header:
            _set_column_role(columns[index], "points", "medium", "적립 포인트는 이용금액과 분리합니다.")


def _repair_kb_bizcard_statement_columns(columns: list[dict[str, Any]]) -> None:
    headers = [_norm(str(column.get("header", ""))) for column in columns]
    joined = "|".join(headers)
    if "이번달결제금액" not in joined or not any("포인트리" in header for header in headers):
        return
    if not any("가맹점소재지" in header for header in headers):
        return

    for index, header in enumerate(headers):
        if header == "이용카드":
            _set_column_role(columns[index], "card_label", "high", "KB 사업자카드 표의 카드번호 열로 보정합니다.")
        elif header == "이용일":
            _set_column_role(columns[index], "date", "high", "KB 사업자카드 표의 이용일 열로 보정합니다.")
        elif header in {"이용가맹점", "가맹점명"}:
            _set_column_role(columns[index], "merchant", "high", "KB 사업자카드 표의 가맹점 열로 보정합니다.")
        elif "가맹점소재지" in header:
            _set_column_role(columns[index], "extra", "medium", "가맹점 소재지는 거래처가 아닌 보조 원본 필드로 남깁니다.")
        elif header == "이용금액":
            _set_column_role(columns[index], "amount", "high", "KB 사업자카드 표의 이용금액 열로 보정합니다.")
        elif header == "현지금액":
            _set_column_role(columns[index], "foreign_amount", "medium", "현지금액은 해외 보조 금액으로 분리합니다.")
        elif header == "이번달결제금액":
            _set_column_role(columns[index], "billing_amount", "high", "KB 사업자카드 표의 이번달 결제금액 열로 보정합니다.")
        elif "포인트리" in header:
            _set_column_role(columns[index], "points", "medium", "적립예정 포인트리는 거래 이용금액과 분리합니다.")


def _repair_kb_bizcard_shifted_columns(columns: list[dict[str, Any]]) -> None:
    headers = [_norm(str(column.get("header", ""))) for column in columns]
    if headers != ["이용일", "이용시간", "가맹점명", "가맹점주소", "이용금액", "결제금액", "할부"]:
        return
    roles = ["card_label", "date", "merchant", "extra", "amount", "billing_amount", "extra"]
    reasons = [
        "KB 사업자카드 표에서 첫 열이 카드번호로 밀려 읽힌 행을 보정합니다.",
        "KB 사업자카드 표에서 두 번째 열의 4자리 월일을 이용일로 보정합니다.",
        "KB 사업자카드 표의 가맹점 열로 보정합니다.",
        "가맹점 주소는 보조 원본 필드로 남깁니다.",
        "KB 사업자카드 표의 이용금액 열로 보정합니다.",
        "KB 사업자카드 표의 결제금액 열로 보정합니다.",
        "밀림 헤더의 마지막 열은 거래 핵심 금액에서 제외합니다.",
    ]
    for index, role in enumerate(roles):
        _set_column_role(columns[index], role, "high" if role in CORE_FIELDS else "medium", reasons[index])


def _repair_samsung_billing_statement_columns(columns: list[dict[str, Any]]) -> None:
    headers = [_norm(str(column.get("header", ""))) for column in columns]
    joined = "|".join(headers)
    if {"이용일", "이용카드", "가맹점", "이용금액", "원금", "이용혜택", "혜택금액"}.issubset(set(headers)):
        for index, header in enumerate(headers):
            if header == "이용일":
                _set_column_role(columns[index], "date", "high", "삼성카드 page 표의 이용일 열로 보정합니다.")
            elif header == "이용카드":
                _set_column_role(columns[index], "card_label", "high", "삼성카드 page 표의 카드 식별 열로 보정합니다.")
            elif header == "가맹점":
                _set_column_role(columns[index], "merchant", "high", "삼성카드 page 표의 가맹점 열로 보정합니다.")
            elif header == "이용금액":
                _set_column_role(columns[index], "extra", "medium", "삼성카드 page 표에서는 원거래 이용금액을 보조 원본 필드로 남깁니다.")
            elif header == "원금":
                _set_column_role(columns[index], "amount", "high", "삼성카드 page 표의 원금 열을 검산 기준 금액으로 보정합니다.")
            elif header == "이용혜택":
                _set_column_role(columns[index], "points", "medium", "이용혜택 설명은 보조 혜택 필드로 남깁니다.")
            elif header == "혜택금액":
                _set_column_role(columns[index], "discount", "medium", "혜택금액은 원금과 분리된 할인/혜택 금액입니다.")
            elif header in {"포인트명", "적립금액"}:
                _set_column_role(columns[index], "points", "medium", "포인트 정보는 거래 원금과 분리합니다.")
        return

    if "입금하실금액" not in joined:
        return

    has_card_number = any("카드번호" in header or "계약번호" in header or header == "이용카드" for header in headers)
    has_merchant_column = any(header in {"가맹점", "가맹점명", "이용건", "이용내역", "이용가맹점", "이용가맹점명"} for header in headers)

    for index, header in enumerate(headers):
        if header == "이용자":
            if has_card_number:
                _set_column_role(columns[index], "extra", "medium", "이용자 표기는 카드 식별 보조 필드로 남깁니다.")
            elif has_merchant_column:
                _set_column_role(columns[index], "card_label", "high", "이용자 값이 본인/가족 및 카드 번호 표기로 안정적입니다.")
        elif header in {"가맹점", "가맹점명", "이용건", "이용내역", "이용가맹점", "이용가맹점명"}:
            _set_column_role(columns[index], "merchant", "high", "삼성카드 표의 이용처 열로 보정합니다.")
        elif "이용금액" in header:
            _set_column_role(columns[index], "extra", "medium", "삼성카드 표에서는 원거래 이용금액을 보조 원본 필드로 남깁니다.")
        elif "이용일수" in header:
            _set_column_role(columns[index], "extra", "medium", "이용일수는 거래 날짜가 아닌 기간 보조 필드입니다.")
        elif "이자" in header or "수수료" in header:
            _set_column_role(columns[index], "fee", "medium", "이자/수수료 열은 검산 기준 원금과 분리합니다.")
        elif "입금하실금액" in header:
            _set_column_role(columns[index], "amount", "high", "삼성카드 표의 이달 입금 금액을 검산 기준 금액으로 보정합니다.")
        elif header in {"입금후", "입금후남은금액", "비고", "적요", "결제종류"}:
            _set_column_role(columns[index], "extra", "medium", "검산 핵심 열이 아닌 보조 설명 필드로 보정합니다.")
        elif "적립금액" in header:
            _set_column_role(columns[index], "points", "medium", "포인트 적립 금액은 거래 이용금액과 분리합니다.")
        elif "할인" in header or "혜택" in header:
            _set_column_role(columns[index], "discount", "medium", "할인/혜택 금액 열을 이용금액과 분리합니다.")
        elif header == "금액" and index > 0 and any(token in headers[index - 1] for token in ("할인", "혜택", "상세")):
            _set_column_role(columns[index], "discount", "medium", "할인 설명 다음의 금액 열을 할인 금액으로 보정합니다.")


def _set_column_role(column: dict[str, Any], field: str, confidence: str, reason: str) -> None:
    column["suggested_field"] = field
    column["confidence"] = confidence
    column["reason"] = reason


def _first_index(columns: list[dict[str, Any]], start: int, stop: int, predicate: Any) -> int | None:
    for index in range(start, min(stop, len(columns))):
        if _sample_rate(columns[index], predicate) >= 0.6:
            return index
    return None


def _has_stable_statement_headers(headers: list[str]) -> bool:
    joined = "|".join(headers)
    has_card = any("카드" in header or "card" in header for header in headers)
    has_merchant = any("가맹점" in header or "merchant" in header for header in headers)
    has_amount = any(header in {"이용금액", "금액", "amount"} for header in headers)
    has_billing = any("결제원금" in header or "청구금액" in header or "billing" in header for header in headers)
    return has_card and has_merchant and has_amount and has_billing and "이용내용" not in joined


def _card_label_index(columns: list[dict[str, Any]]) -> int | None:
    candidates: list[int] = []
    for index in range(1, min(3, len(columns))):
        if _sample_rate(columns[index], _is_card_label_like) >= 0.6:
            candidates.append(index)
    if not candidates:
        return None
    for index in candidates:
        if _sample_rate(columns[index], _is_owner_marker) < 0.8:
            return index
    return candidates[0]


def _sample_rate(column: dict[str, Any], predicate: Any) -> float:
    values = [str(value).strip() for value in column.get("sample_values", []) if str(value).strip()]
    if not values:
        return 0.0
    return sum(1 for value in values if predicate(value)) / len(values)


def _same_value_as(other_column: dict[str, Any]) -> Any:
    other_values = [
        _money_value(str(value).strip())
        for value in other_column.get("sample_values", [])
        if str(value).strip()
    ]

    def predicate(value: str) -> bool:
        current = _money_value(value)
        return current is not None and current in other_values

    return predicate


def _has_discounted_payable_pattern(amount_column: dict[str, Any], discount_column: dict[str, Any], payable_column: dict[str, Any]) -> bool:
    amounts = [_money_value(str(value).strip()) for value in amount_column.get("sample_values", [])]
    discounts = [_money_value(str(value).strip()) for value in discount_column.get("sample_values", [])]
    payables = [_money_value(str(value).strip()) for value in payable_column.get("sample_values", [])]
    matches = 0
    checked = 0
    for amount, discount, payable in zip(amounts, discounts, payables):
        if amount is None or discount is None or payable is None:
            continue
        checked += 1
        if amount - discount == payable:
            matches += 1
    return checked >= 3 and matches / checked >= 0.8


def _is_installment_round_like(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}/\d{1,2}", value.strip()))


def _is_benefit_value_like(value: str) -> bool:
    text = value.strip()
    return bool(re.fullmatch(r"[\d,]+(?:\([^)]*\))?", text))


def _money_value(value: str) -> int | None:
    if not _is_money_like(value):
        return None
    digits = re.sub(r"[^0-9-]", "", value)
    if digits in {"", "-"}:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _is_card_label_like(value: str) -> bool:
    text = re.sub(r"\s+", " ", value.strip()).lower()
    return any(token in text for token in ("본인", "가족", "zero", "purple", "포인트형", "카드"))


def _is_owner_marker(value: str) -> bool:
    return re.sub(r"\s+", "", value.strip()) in {"본인", "가족"}


def _is_text_like_not_money(value: str) -> bool:
    return bool(re.search(r"[A-Za-z가-힣]", value)) and not _is_money_like(value)


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
    if any(token in text for token in ("해외이용금액", "접수금액", "foreignamount")):
        return _suggest("foreign_amount", "high", "헤더가 해외 이용 금액 열처럼 보입니다.")
    if any(token in text for token in ("환율", "exchangerate")):
        return _suggest("exchange_rate", "high", "헤더가 환율 열처럼 보입니다.")
    if any(token in text for token in ("국가", "country")):
        return _suggest("memo", "medium", "헤더가 국가 정보 열처럼 보입니다.")
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


def _table_signature(group: dict[str, Any]) -> dict[str, Any]:
    columns = [column for column in group.get("columns", []) if isinstance(column, dict)]
    header = [str(value) for value in group.get("header", [])]
    if not header:
        header = [str(column.get("header", "")) for column in columns]
    header_tokens = [_header_tokens(value) for value in header]
    suggested_fields = [
        str(column.get("selected_field") or column.get("suggested_field") or "")
        for column in columns
    ]
    sample_patterns = [_sample_pattern(column) for column in columns]
    return {
        "column_count": len(columns) or len(header),
        "header_tokens": header_tokens,
        "suggested_fields": suggested_fields,
        "date_like_indexes": _field_indexes(columns, {"date"}),
        "money_like_indexes": _field_indexes(
            columns,
            {"amount", "billing_amount", "discount", "fee", "points", "foreign_amount"},
        ),
        "text_heavy_indexes": _field_indexes(columns, {"merchant", "card_label", "memo", "extra"}),
        "sample_patterns": sample_patterns,
    }


def _signature_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_count = int(left.get("column_count", 0) or 0)
    right_count = int(right.get("column_count", 0) or 0)
    if not left_count or not right_count:
        return 0.0

    column_score = 1.0 if left_count == right_count else max(0.0, 1.0 - abs(left_count - right_count) / max(left_count, right_count))
    header_score = _header_similarity(
        _as_token_lists(left.get("header_tokens")),
        _as_token_lists(right.get("header_tokens")),
    )
    field_score = _sequence_similarity(
        [str(value) for value in left.get("suggested_fields", [])],
        [str(value) for value in right.get("suggested_fields", [])],
    )
    date_score = _set_similarity(left.get("date_like_indexes", []), right.get("date_like_indexes", []))
    money_score = _set_similarity(left.get("money_like_indexes", []), right.get("money_like_indexes", []))
    text_score = _set_similarity(left.get("text_heavy_indexes", []), right.get("text_heavy_indexes", []))
    pattern_score = _sequence_similarity(
        [str(value) for value in left.get("sample_patterns", [])],
        [str(value) for value in right.get("sample_patterns", [])],
    )
    if _patterns_missing(left.get("sample_patterns")) or _patterns_missing(right.get("sample_patterns")):
        pattern_score = 1.0
    score = (
        column_score * 0.18
        + header_score * 0.20
        + field_score * 0.22
        + date_score * 0.10
        + money_score * 0.12
        + text_score * 0.08
        + pattern_score * 0.10
    )
    return round(score, 4)


def _patterns_missing(value: Any) -> bool:
    patterns = [str(item) for item in value or []]
    return not patterns or all(item == "empty" for item in patterns)


def _header_similarity(left_tokens: list[list[str]], right_tokens: list[list[str]]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    total = max(len(left_tokens), len(right_tokens))
    matches = 0.0
    for index in range(total):
        left = set(left_tokens[index]) if index < len(left_tokens) else set()
        right = set(right_tokens[index]) if index < len(right_tokens) else set()
        if not left and not right:
            matches += 1.0
        elif left and right:
            matches += len(left & right) / len(left | right)
    return matches / total


def _sequence_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    total = max(len(left), len(right))
    matches = 0
    for index in range(total):
        if index < len(left) and index < len(right) and left[index] == right[index]:
            matches += 1
    return matches / total


def _set_similarity(left: Any, right: Any) -> float:
    left_set = {int(value) for value in left or []}
    right_set = {int(value) for value in right or []}
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _field_indexes(columns: list[dict[str, Any]], fields: set[str]) -> list[int]:
    indexes: list[int] = []
    for index, column in enumerate(columns):
        field = str(column.get("selected_field") or column.get("suggested_field") or "")
        if field in fields:
            indexes.append(index)
    return indexes


def _sample_pattern(column: dict[str, Any]) -> str:
    values = [str(value) for value in column.get("sample_values", []) if str(value).strip()]
    if not values:
        return "empty"
    date_rate = sum(1 for value in values if _is_date_like(value)) / len(values)
    money_rate = sum(1 for value in values if _is_money_like(value)) / len(values)
    text_rate = sum(1 for value in values if re.search(r"[A-Za-z가-힣]", value)) / len(values)
    if date_rate >= 0.6:
        return "date"
    if money_rate >= 0.7:
        return "money"
    if text_rate >= 0.7:
        return "text"
    return "mixed"


def _header_tokens(value: str) -> list[str]:
    text = _norm(value)
    aliases = {
        "date": ("이용일", "승인일", "매출일", "일자", "date"),
        "card": ("카드", "카드명", "카드번호", "card"),
        "merchant": ("가맹점", "가맹점명", "이용처", "사용처", "merchant"),
        "amount": ("이용금액", "사용금액", "승인금액", "금액", "amount"),
        "billing": ("결제원금", "청구금액", "입금하실금액", "billing"),
        "fee": ("수수료", "이자", "fee"),
        "benefit": ("혜택", "할인", "포인트"),
        "installment": ("할부", "회차", "개월"),
    }
    tokens = [key for key, words in aliases.items() if any(_norm(word) in text for word in words)]
    if tokens:
        return tokens
    return [text] if text else []


def _as_token_lists(value: Any) -> list[list[str]]:
    token_lists: list[list[str]] = []
    for item in value or []:
        if isinstance(item, list):
            token_lists.append([str(token) for token in item])
        else:
            token_lists.append([str(item)])
    return token_lists


def _header_key(header: list[str]) -> str:
    if not header:
        return "unknown_header"
    return "|".join(_norm(value) for value in header)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value).strip().lower())


def _is_date_like(value: str) -> bool:
    value = value.strip()
    return bool(
        re.fullmatch(r"\d{1,2}[./-]\d{1,2}", value)
        or re.fullmatch(r"\d{2}[./-]\d{1,2}[./-]\d{1,2}", value)
        or re.fullmatch(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", value)
    )


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
