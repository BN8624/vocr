from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.chunk_builder import ChunkImage
from src.vision_extractor import VisionResult


@dataclass(frozen=True)
class RowMergeOutput:
    rows_raw_path: Path
    rows_merged_path: Path
    summary_path: Path
    raw_row_count: int
    merged_row_count: int
    duplicate_group_count: int
    duplicate_row_count: int
    duplicate_index: dict[tuple[str, int], str]
    duplicate_decision_index: dict[tuple[str, int], dict[str, Any]]
    summary: dict[str, Any]


def build_row_outputs(
    vision_results: list[VisionResult],
    chunks: list[ChunkImage],
    input_pdf: Path,
    output_dir: Path,
    merged_dir: Path,
) -> RowMergeOutput:
    merged_dir.mkdir(parents=True, exist_ok=True)
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    raw_rows = _collect_raw_rows(
        vision_results=vision_results,
        chunk_by_id=chunk_by_id,
        input_pdf=input_pdf,
        output_dir=output_dir,
    )
    duplicate_groups = _find_duplicate_candidates(raw_rows)
    duplicate_index = _duplicate_index(duplicate_groups)
    duplicate_decision_index = _duplicate_decision_index(duplicate_groups)
    merged_rows = [_with_merge_metadata(row, duplicate_decision_index) for row in raw_rows]

    rows_raw_path = merged_dir / "rows_raw.jsonl"
    rows_merged_path = merged_dir / "rows_merged.jsonl"
    summary_path = merged_dir / "merge_summary.json"

    _write_jsonl(rows_raw_path, raw_rows)
    _write_jsonl(rows_merged_path, merged_rows)

    duplicate_excluded_count = sum(len(group.get("excluded_rows", [])) for group in duplicate_groups)
    duplicate_review_count = sum(
        1
        for group in duplicate_groups
        for row in group.get("rows", [])
        if row.get("decision") == "needs_review"
    )
    representative_count = sum(1 for group in duplicate_groups if group.get("representative"))

    summary = {
        "schema_version": "1.0",
        "raw_row_count": len(raw_rows),
        "merged_row_count": len(merged_rows),
        "transaction_candidate_count": len(raw_rows) - duplicate_excluded_count,
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_row_count": sum(len(group["rows"]) for group in duplicate_groups),
        "representative_count": representative_count,
        "duplicate_excluded_count": duplicate_excluded_count,
        "duplicate_review_count": duplicate_review_count,
        "strategy": "phase_4_representative_selection_exact_duplicates",
        "duplicate_groups": duplicate_groups,
        "outputs": {
            "rows_raw": str(rows_raw_path),
            "rows_merged": str(rows_merged_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return RowMergeOutput(
        rows_raw_path=rows_raw_path,
        rows_merged_path=rows_merged_path,
        summary_path=summary_path,
        raw_row_count=len(raw_rows),
        merged_row_count=len(merged_rows),
        duplicate_group_count=len(duplicate_groups),
        duplicate_row_count=summary["duplicate_row_count"],
        duplicate_index=duplicate_index,
        duplicate_decision_index=duplicate_decision_index,
        summary=summary,
    )


def load_merge_output(merged_dir: Path) -> RowMergeOutput | None:
    summary_path = merged_dir / "merge_summary.json"
    rows_raw_path = merged_dir / "rows_raw.jsonl"
    rows_merged_path = merged_dir / "rows_merged.jsonl"
    if not summary_path.exists():
        return None

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    duplicate_groups = summary.get("duplicate_groups", [])
    duplicate_index = _duplicate_index(duplicate_groups)
    duplicate_decision_index = _duplicate_decision_index(duplicate_groups)
    return RowMergeOutput(
        rows_raw_path=rows_raw_path,
        rows_merged_path=rows_merged_path,
        summary_path=summary_path,
        raw_row_count=int(summary.get("raw_row_count", 0)),
        merged_row_count=int(summary.get("merged_row_count", 0)),
        duplicate_group_count=int(summary.get("duplicate_group_count", 0)),
        duplicate_row_count=int(summary.get("duplicate_row_count", 0)),
        duplicate_index=duplicate_index,
        duplicate_decision_index=duplicate_decision_index,
        summary=summary,
    )


def _collect_raw_rows(
    vision_results: list[VisionResult],
    chunk_by_id: dict[str, ChunkImage],
    input_pdf: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for result in vision_results:
        if not result.data:
            continue

        chunk = chunk_by_id.get(result.chunk_id)
        header = [str(value) for value in result.data.get("header", [])]
        rows = [row for row in result.data.get("rows", []) if isinstance(row, dict)]

        for fallback_index, row in enumerate(rows, start=1):
            local_index = _safe_int(row.get("local_row_index"), fallback_index)
            cells = [str(value) for value in row.get("cells", [])]
            image_ref = ""
            if chunk:
                image_ref = _safe_relative(output_dir, chunk.image_path)

            records.append(
                {
                    "schema_version": "1.0",
                    "source": {
                        "file": input_pdf.name,
                        "page": int(result.data.get("page") or result.page_number),
                        "chunk_id": result.chunk_id,
                        "local_row_index": local_index,
                        "statement_type": "unknown",
                        "period": "",
                    },
                    "raw": {
                        "header": header,
                        "cells": cells,
                        "line_text": str(row.get("line_text", "")),
                        "image_ref": image_ref,
                    },
                    "transaction": {
                        "date": "",
                        "card_label": "",
                        "merchant": "",
                        "amount": None,
                        "billing_amount": None,
                        "transaction_type": "",
                    },
                    "extra_fields": {},
                    "quality": {
                        "needs_review": bool(row.get("needs_review", False)),
                        "review_reason": str(row.get("review_reason", "")),
                        "confidence_note": str(row.get("confidence_note", "")),
                    },
                    "merge": {
                        "decision": "keep",
                        "duplicate_group_id": "",
                        "review_reason": "",
                    },
                }
            )
    return records


def _find_duplicate_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source = row["source"]
        fingerprint = _fingerprint(row["raw"]["cells"])
        if not fingerprint:
            continue
        grouped[(int(source["page"]), fingerprint)].append(row)

    groups: list[dict[str, Any]] = []
    group_number = 1
    for (page, fingerprint), candidates in grouped.items():
        chunk_ids = {row["source"]["chunk_id"] for row in candidates}
        if len(candidates) < 2 or len(chunk_ids) < 2:
            continue

        auto_resolve = _looks_like_overlap_duplicate(candidates)
        representative = _choose_representative(candidates) if auto_resolve else None
        representative_key = _row_key(representative) if representative else None
        row_entries = []
        for row in candidates:
            if not auto_resolve:
                decision = "needs_review"
            else:
                decision = "representative" if _row_key(row) == representative_key else "duplicate_excluded"
            row_entries.append(
                {
                    "chunk_id": row["source"]["chunk_id"],
                    "local_row_index": row["source"]["local_row_index"],
                    "cells": row["raw"]["cells"],
                    "decision": decision,
                    "score": list(_representative_score(row)),
                }
            )

        groups.append(
            {
                "group_id": f"dup_{group_number:03d}",
                "page": page,
                "decision": "auto_representative_selected" if auto_resolve else "needs_review",
                "reason": (
                    "서로 다른 겹침 청크에서 같은 raw cells가 반복되어 대표행 1개만 거래로 사용합니다. 제외행은 원본셀 보존용으로만 남깁니다."
                    if auto_resolve
                    else "서로 떨어진 청크에서 같은 raw cells가 발견되었습니다. 실제 반복 거래일 수 있어 자동 제외하지 않습니다."
                ),
                "fingerprint": fingerprint,
                "representative": (
                    {
                        "chunk_id": representative["source"]["chunk_id"],
                        "local_row_index": representative["source"]["local_row_index"],
                    }
                    if representative
                    else {}
                ),
                "excluded_rows": [
                    {
                        "chunk_id": row["chunk_id"],
                        "local_row_index": row["local_row_index"],
                    }
                    for row in row_entries
                    if row["decision"] == "duplicate_excluded"
                ],
                "rows": row_entries,
            }
        )
        group_number += 1
    return groups


def _with_merge_metadata(
    row: dict[str, Any],
    duplicate_decision_index: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    copied = json.loads(json.dumps(row, ensure_ascii=False))
    source = copied["source"]
    key = (source["chunk_id"], int(source["local_row_index"]))
    duplicate = duplicate_decision_index.get(key, {})
    group_id = str(duplicate.get("group_id", ""))
    decision = str(duplicate.get("decision", ""))
    if group_id:
        copied["merge"] = {
            "decision": decision,
            "duplicate_group_id": group_id,
            "review_reason": _merge_reason(decision, group_id),
        }
        if decision == "needs_review":
            copied["quality"]["needs_review"] = True
            existing = copied["quality"].get("review_reason", "")
            duplicate_reason = f"중복 확인필요 {group_id}"
            copied["quality"]["review_reason"] = (
                f"{existing}; {duplicate_reason}" if existing else duplicate_reason
            )
    return copied


def _duplicate_index(duplicate_groups: list[dict[str, Any]]) -> dict[tuple[str, int], str]:
    index: dict[tuple[str, int], str] = {}
    for group in duplicate_groups:
        group_id = str(group.get("group_id", ""))
        for row in group.get("rows", []):
            index[(str(row["chunk_id"]), int(row["local_row_index"]))] = group_id
    return index


def _duplicate_decision_index(
    duplicate_groups: list[dict[str, Any]],
) -> dict[tuple[str, int], dict[str, Any]]:
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for group in duplicate_groups:
        group_id = str(group.get("group_id", ""))
        for row in group.get("rows", []):
            index[(str(row["chunk_id"]), int(row["local_row_index"]))] = {
                "group_id": group_id,
                "decision": str(row.get("decision", "needs_review")),
            }
    return index


def _choose_representative(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=_representative_score)


def _representative_score(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
    quality = row.get("quality", {})
    raw = row.get("raw", {})
    cells = [str(value).strip() for value in raw.get("cells", [])]
    source = row.get("source", {})
    return (
        0 if quality.get("needs_review") else 1,
        sum(1 for cell in cells if cell),
        len(str(raw.get("line_text", ""))),
        len(cells),
        -int(source.get("local_row_index", 0) or 0),
    )


def _row_key(row: dict[str, Any]) -> tuple[str, int]:
    source = row["source"]
    return (str(source["chunk_id"]), int(source["local_row_index"]))


def _looks_like_overlap_duplicate(rows: list[dict[str, Any]]) -> bool:
    indexes = [_chunk_index(str(row.get("source", {}).get("chunk_id", ""))) for row in rows]
    if any(index is None for index in indexes):
        return False
    unique_indexes = sorted({int(index) for index in indexes if index is not None})
    return bool(unique_indexes) and unique_indexes[-1] - unique_indexes[0] <= 1


def _chunk_index(chunk_id: str) -> int | None:
    match = re.search(r"_chunk_(\d+)$", chunk_id)
    if not match:
        return None
    return int(match.group(1))


def _merge_reason(decision: str, group_id: str) -> str:
    if decision == "representative":
        return f"겹침 청크 중복 그룹 {group_id}의 대표행입니다."
    if decision == "duplicate_excluded":
        return f"겹침 청크 중복 그룹 {group_id}에서 대표행이 선택되어 거래 합계와 전체명세에서는 제외됩니다."
    return f"겹침 청크 중복 그룹 {group_id} 확인이 필요합니다."


def _fingerprint(cells: list[str]) -> str:
    normalized = [_normalize_cell(cell) for cell in cells]
    normalized = [cell for cell in normalized if cell]
    return "|".join(normalized)


def _normalize_cell(value: str) -> str:
    value = str(value).strip().lower()
    value = re.sub(r"\s+", "", value)
    value = value.replace(",", "")
    return value


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _safe_relative(base_dir: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return str(target)


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
