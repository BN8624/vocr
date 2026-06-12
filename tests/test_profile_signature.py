from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunk_builder import ChunkImage
from src.profile_store import build_mapping_suggestions
from src.row_merger import build_row_outputs
from src.vision_extractor import VisionResult


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        output_dir = root / "output"
        merged_dir = output_dir / "merged"
        profiles_dir = root / "profiles"
        output_dir.mkdir()
        profiles_dir.mkdir()

        _write_profile(
            profiles_dir / "mapping-profile.json",
            ["승인일", "카드명", "이용처", "승인금액"],
        )
        merge_output = build_row_outputs(
            vision_results=[
                _vision(
                    ["이용일", "카드", "가맹점명", "이용금액"],
                    [
                        ["03.14", "the Purple", "쿠팡", "10,000"],
                        ["03.15", "the Purple", "편의점", "12,000"],
                    ],
                )
            ],
            chunks=[_chunk()],
            input_pdf=root / "sample.pdf",
            output_dir=output_dir,
            merged_dir=merged_dir,
        )

        mapping = build_mapping_suggestions(
            merge_output=merge_output,
            output_dir=output_dir,
            profiles_dir=profiles_dir,
        )
        assert mapping is not None
        group = mapping.table_groups[0]
        assert group["profile_match"]["status"] == "auto"
        selected = [column["selected_field"] for column in group["columns"]]
        assert selected == ["date", "card_label", "merchant", "amount"]
        assert mapping.applied_profiles

        _write_profile(
            profiles_dir / "weak-profile.json",
            ["날짜", "이용카드", "가맹점", "금액", "혜택"],
        )
        weak_match = _candidate_group(root / "weak", profiles_dir / "weak-profile.json")
        assert weak_match["profile_match"]["status"] == "candidate"

    print("profile signature test passed")
    return 0


def _candidate_group(root: Path, profile_path: Path) -> dict[str, object]:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    profiles_dir = root / "profiles"
    output_dir.mkdir(parents=True)
    profiles_dir.mkdir(parents=True)
    profiles_dir.joinpath("weak-profile.json").write_text(profile_path.read_text(encoding="utf-8"), encoding="utf-8")
    merge_output = build_row_outputs(
        vision_results=[
            _vision(
                ["이용일", "이용카드", "가맹점", "이용금액"],
                [
                    ["03.14", "card", "store", "10,000"],
                    ["03.15", "card", "shop", "20,000"],
                ],
            )
        ],
        chunks=[_chunk()],
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    mapping = build_mapping_suggestions(
        merge_output=merge_output,
        output_dir=output_dir,
        profiles_dir=profiles_dir,
    )
    assert mapping is not None
    return mapping.table_groups[0]


def _write_profile(path: Path, header: list[str]) -> None:
    fields = ["date", "card_label", "merchant", "amount", "extra"]
    payload = {
        "schema_version": "1.0",
        "status": "user_confirmed_saved",
        "table_groups": [
            {
                "group_id": "|".join(header),
                "header": header,
                "columns": [
                    {
                        "column_id": f"col_{index + 1}",
                        "header": label,
                        "selected_field": fields[index],
                        "suggested_field": fields[index],
                    }
                    for index, label in enumerate(header)
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _chunk() -> ChunkImage:
    return ChunkImage(
        chunk_id="page_001_chunk_01",
        page_number=1,
        chunk_index=1,
        image_path=Path("chunk.png"),
        width=100,
        height=100,
        source_y_start=0,
        source_y_end=100,
        header_y_start=0,
        header_y_end=10,
        reused=False,
    )


def _vision(header: list[str], rows: list[list[str]]) -> VisionResult:
    return VisionResult(
        chunk_id="page_001_chunk_01",
        page_number=1,
        cache_path=Path("page_001_chunk_01.vision.json"),
        status="cached",
        data={
            "schema_version": "1.0",
            "page": 1,
            "chunk_id": "page_001_chunk_01",
            "header": header,
            "rows": [
                {
                    "local_row_index": index,
                    "cells": cells,
                    "line_text": " ".join(cells),
                    "needs_review": False,
                    "review_reason": "",
                    "confidence_note": "",
                }
                for index, cells in enumerate(rows, start=1)
            ],
            "totals": [],
            "needs_review": False,
            "review_reason": "",
            "notes": "",
        },
        reused=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
