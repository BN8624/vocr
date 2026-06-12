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
    merged_rows = [_with_merge_metadata(row, duplicate_index) for row in raw_rows]

    rows_raw_path = merged_dir / "rows_raw.jsonl"
    rows_merged_path = merged_dir / "rows_merged.jsonl"
    summary_path = merged_dir / "merge_summary.json"

    _write_jsonl(rows_raw_path, raw_rows)
    _write_jsonl(rows_merged_path, merged_rows)

    summary = {
        "schema_version": "1.0",
        "raw_row_count": len(raw_rows),
        "merged_row_count": len(merged_rows),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_row_count": sum(len(group["rows"]) for group in duplicate_groups),
        "strategy": "phase_4_candidate_only_no_rows_removed",
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
    return RowMergeOutput(
        rows_raw_path=rows_raw_path,
        rows_merged_path=rows_merged_path,
        summary_path=summary_path,
        raw_row_count=int(summary.get("raw_row_count", 0)),
        merged_row_count=int(summary.get("merged_row_count", 0)),
        duplicate_group_count=int(summary.get("duplicate_group_count", 0)),
        duplicate_row_count=int(summary.get("duplicate_row_count", 0)),
        duplicate_index=duplicate_index,
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

        groups.append(
            {
                "group_id": f"dup_{group_number:03d}",
                "page": page,
                "decision": "needs_review",
                "reason": "서로 다른 청크에서 같은 raw cells가 반복 추출되었습니다. 아직 자동 삭제하지 않습니다.",
                "fingerprint": fingerprint,
                "rows": [
                    {
                        "chunk_id": row["source"]["chunk_id"],
                        "local_row_index": row["source"]["local_row_index"],
                        "cells": row["raw"]["cells"],
                    }
                    for row in candidates
                ],
            }
        )
        group_number += 1
    return groups


def _with_merge_metadata(
    row: dict[str, Any],
    duplicate_index: dict[tuple[str, int], str],
) -> dict[str, Any]:
    copied = json.loads(json.dumps(row, ensure_ascii=False))
    source = copied["source"]
    key = (source["chunk_id"], int(source["local_row_index"]))
    group_id = duplicate_index.get(key, "")
    if group_id:
        copied["merge"] = {
            "decision": "needs_review",
            "duplicate_group_id": group_id,
            "review_reason": "겹치는 청크에서 반복 추출된 중복 후보입니다.",
        }
        copied["quality"]["needs_review"] = True
        existing = copied["quality"].get("review_reason", "")
        duplicate_reason = f"중복 후보 {group_id}"
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
