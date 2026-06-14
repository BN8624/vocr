from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunk_builder import ChunkImage
from src.normalizer import build_transactions
from src.profile_store import MappingOutput
from src.row_merger import build_row_outputs
from src.vision_extractor import VisionResult


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        output_dir = root / "output"
        merged_dir = output_dir / "merged"
        output_dir.mkdir()

        chunks = [
            _chunk("page_001_chunk_01", root / "chunk_01.png", 1),
            _chunk("page_001_chunk_02", root / "chunk_02.png", 2),
        ]
        vision_results = [
            _vision(
                "page_001_chunk_01",
                [
                    ["03.14", "the Purple", "쿠팡", "10,000", "10,000"],
                    ["03.15", "the Purple", "편의점", "5,000", "5,000"],
                ],
            ),
            _vision(
                "page_001_chunk_02",
                [
                    ["03.14", "the Purple", "쿠팡", "10,000", "10,000"],
                ],
            ),
        ]

        merge_output = build_row_outputs(
            vision_results=vision_results,
            chunks=chunks,
            input_pdf=root / "sample.pdf",
            output_dir=output_dir,
            merged_dir=merged_dir,
        )

        merged_rows = _read_jsonl(merge_output.rows_merged_path)
        decisions = [row["merge"]["decision"] for row in merged_rows]
        assert decisions.count("representative") == 1, decisions
        assert decisions.count("duplicate_excluded") == 1, decisions
        assert decisions.count("keep") == 1, decisions
        assert merge_output.summary["duplicate_excluded_count"] == 1
        assert merge_output.summary["transaction_candidate_count"] == 2

        mapping_output = MappingOutput(
            suggestions_path=merged_dir / "mapping_suggestions.json",
            profile_dir=root / "profiles",
            table_groups=[_mapping_group()],
            option_labels={},
            applied_profiles=[],
        )
        normalization_output = build_transactions(
            merge_output=merge_output,
            mapping_output=mapping_output,
            merged_dir=merged_dir,
        )

        assert normalization_output is not None
        assert normalization_output.transaction_count == 2
        assert normalization_output.amount_total == 15000
        assert normalization_output.summary["duplicate_excluded_count"] == 1

        _assert_non_adjacent_duplicates_need_review(root / "non_adjacent")
        _assert_normalized_variant_duplicates_excluded(root / "normalized_variant")
        _assert_same_amount_different_merchants_kept(root / "different_merchants")
        _assert_merchant_ocr_variant_duplicate_excluded(root / "merchant_ocr_variant")
        _assert_installment_variant_duplicates_excluded(root / "installment_variant")
        _assert_hyundai_combined_header_row_repaired(root / "hyundai_combined_header")
        _assert_hyundai_billing_amount_repaired_from_header(root / "hyundai_billing_header")
        _assert_hyundai_split_content_row_repaired(root / "hyundai_split_content")

    print("duplicate representative test passed")
    return 0


def _chunk(chunk_id: str, image_path: Path, chunk_index: int, page_number: int = 1) -> ChunkImage:
    return ChunkImage(
        chunk_id=chunk_id,
        page_number=page_number,
        chunk_index=chunk_index,
        image_path=image_path,
        width=100,
        height=100,
        source_y_start=0,
        source_y_end=100,
        header_y_start=0,
        header_y_end=10,
        reused=False,
    )


def _vision(chunk_id: str, cells_list: list[list[str]]) -> VisionResult:
    return VisionResult(
        chunk_id=chunk_id,
        page_number=1,
        cache_path=Path(f"{chunk_id}.vision.json"),
        status="cached",
        data={
            "schema_version": "1.0",
            "page": 1,
            "chunk_id": chunk_id,
            "header": ["이용일", "이용카드", "이용가맹점", "이용금액", "결제원금"],
            "rows": [
                {
                    "local_row_index": index,
                    "cells": cells,
                    "line_text": " ".join(cells),
                    "needs_review": False,
                    "review_reason": "",
                    "confidence_note": "",
                }
                for index, cells in enumerate(cells_list, start=1)
            ],
            "totals": [],
            "needs_review": False,
            "review_reason": "",
            "notes": "",
        },
        reused=True,
    )


def _mapping_group() -> dict[str, object]:
    header = ["이용일", "이용카드", "이용가맹점", "이용금액", "결제원금"]
    fields = ["date", "card_label", "merchant", "amount", "billing_amount"]
    return {
        "group_id": "이용일|이용카드|이용가맹점|이용금액|결제원금",
        "row_count": 3,
        "header": header,
        "columns": [
            {
                "column_index": index,
                "column_id": f"col_{index + 1}",
                "header": label,
                "suggested_field": fields[index],
                "selected_field": fields[index],
                "requires_review": False,
            }
            for index, label in enumerate(header)
        ],
    }


def _assert_non_adjacent_duplicates_need_review(root: Path) -> None:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    output_dir.mkdir(parents=True)
    chunks = [
        _chunk("page_001_chunk_01", root / "chunk_01.png", 1),
        _chunk("page_001_chunk_03", root / "chunk_03.png", 3),
    ]
    vision_results = [
        _vision("page_001_chunk_01", [["03.14", "the Purple", "쿠팡", "10,000", "10,000"]]),
        _vision("page_001_chunk_03", [["03.14", "the Purple", "쿠팡", "10,000", "10,000"]]),
    ]

    merge_output = build_row_outputs(
        vision_results=vision_results,
        chunks=chunks,
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    merged_rows = _read_jsonl(merge_output.rows_merged_path)
    decisions = [row["merge"]["decision"] for row in merged_rows]
    assert decisions == ["needs_review", "needs_review"], decisions
    assert merge_output.summary["duplicate_excluded_count"] == 0
    assert merge_output.summary["duplicate_review_count"] == 2


def _assert_normalized_variant_duplicates_excluded(root: Path) -> None:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    output_dir.mkdir(parents=True)
    chunks = [
        _chunk("page_001_chunk_01", root / "chunk_01.png", 1),
        _chunk("page_001_chunk_02", root / "chunk_02.png", 2),
    ]
    vision_results = [
        _vision_with_header(
            "page_001_chunk_01",
            ["date", "card", "merchant", "amount", "billing"],
            [["03.14", "the Purple", "store", "10,000", "10,000"]],
        ),
        _vision_with_header(
            "page_001_chunk_02",
            ["date", "owner", "card", "merchant", "amount", "points", "billing"],
            [["03.14", "본인", "the Purple", "store", "10,000", "10", "10,000"]],
        ),
    ]
    merge_output = build_row_outputs(
        vision_results=vision_results,
        chunks=chunks,
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    mapping_output = MappingOutput(
        suggestions_path=merged_dir / "mapping_suggestions.json",
        profile_dir=root / "profiles",
        table_groups=[
            _mapping_group_for(["date", "card", "merchant", "amount", "billing"], ["date", "card_label", "merchant", "amount", "billing_amount"]),
            _mapping_group_for(
                ["date", "owner", "card", "merchant", "amount", "points", "billing"],
                ["date", "ignore", "card_label", "merchant", "amount", "points", "billing_amount"],
            ),
        ],
        option_labels={},
        applied_profiles=[],
    )
    normalization_output = build_transactions(
        merge_output=merge_output,
        mapping_output=mapping_output,
        merged_dir=merged_dir,
    )
    assert normalization_output is not None
    assert normalization_output.transaction_count == 1
    assert normalization_output.amount_total == 10000
    assert normalization_output.summary["normalized_duplicate_excluded_count"] == 1


def _assert_same_amount_different_merchants_kept(root: Path) -> None:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    output_dir.mkdir(parents=True)
    chunks = [
        _chunk("page_001_chunk_01", root / "chunk_01.png", 1),
        _chunk("page_001_chunk_02", root / "chunk_02.png", 2),
    ]
    vision_results = [
        _vision_with_header(
            "page_001_chunk_01",
            ["date", "card", "merchant", "amount", "billing"],
            [["03.14", "the Purple", "alpha market", "10,000", "10,000"]],
        ),
        _vision_with_header(
            "page_001_chunk_02",
            ["date", "card", "merchant", "amount", "billing"],
            [["03.14", "the Purple", "beta pharmacy", "10,000", "10,000"]],
        ),
    ]
    merge_output = build_row_outputs(
        vision_results=vision_results,
        chunks=chunks,
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    mapping_output = MappingOutput(
        suggestions_path=merged_dir / "mapping_suggestions.json",
        profile_dir=root / "profiles",
        table_groups=[
            _mapping_group_for(["date", "card", "merchant", "amount", "billing"], ["date", "card_label", "merchant", "amount", "billing_amount"])
        ],
        option_labels={},
        applied_profiles=[],
    )
    normalization_output = build_transactions(
        merge_output=merge_output,
        mapping_output=mapping_output,
        merged_dir=merged_dir,
    )
    assert normalization_output is not None
    assert normalization_output.transaction_count == 2
    assert normalization_output.amount_total == 20000
    assert normalization_output.summary["normalized_duplicate_excluded_count"] == 0


def _assert_merchant_ocr_variant_duplicate_excluded(root: Path) -> None:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    output_dir.mkdir(parents=True)
    chunks = [
        _chunk("page_001_chunk_01", root / "chunk_01.png", 1),
        _chunk("page_001_chunk_02", root / "chunk_02.png", 2),
    ]
    vision_results = [
        _vision_with_header(
            "page_001_chunk_01",
            ["date", "card", "merchant", "amount", "billing"],
            [["03.14", "the Purple", "clear merchant", "10,000", "10,000"]],
        ),
        _vision_with_header(
            "page_001_chunk_02",
            ["date", "card", "merchant", "amount", "billing"],
            [["03.14", "the Purple", "garbled merchant", "10,000", "10,000"]],
            review_reasons=["OCR read error for merchant name"],
        ),
    ]
    merge_output = build_row_outputs(
        vision_results=vision_results,
        chunks=chunks,
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    mapping_output = MappingOutput(
        suggestions_path=merged_dir / "mapping_suggestions.json",
        profile_dir=root / "profiles",
        table_groups=[
            _mapping_group_for(["date", "card", "merchant", "amount", "billing"], ["date", "card_label", "merchant", "amount", "billing_amount"])
        ],
        option_labels={},
        applied_profiles=[],
    )
    normalization_output = build_transactions(
        merge_output=merge_output,
        mapping_output=mapping_output,
        merged_dir=merged_dir,
    )
    assert normalization_output is not None
    assert normalization_output.transaction_count == 1
    assert normalization_output.amount_total == 10000
    assert normalization_output.summary["normalized_duplicate_excluded_count"] == 1


def _assert_installment_variant_duplicates_excluded(root: Path) -> None:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    output_dir.mkdir(parents=True)
    chunks = [
        _chunk("page_001_chunk_01", root / "chunk_01.png", 1),
        _chunk("page_001_chunk_03", root / "chunk_03.png", 3),
    ]
    header = ["이용일자", "이용카드", "이용가맹점", "이용금액", "할부 기간/회차", "이번달 내실 금액 원금"]
    vision_results = [
        _vision_with_header(
            "page_001_chunk_01",
            header,
            [["24.12.07", "본인31*", "쿠팡", "51,980", "5/5", "10,300"]],
        ),
        _vision_with_header(
            "page_001_chunk_03",
            header,
            [["25.04.24", "본인31*", "쿠팡", "51,980", "5/5", "10,300"]],
        ),
    ]
    merge_output = build_row_outputs(
        vision_results=vision_results,
        chunks=chunks,
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    mapping_output = MappingOutput(
        suggestions_path=merged_dir / "mapping_suggestions.json",
        profile_dir=root / "profiles",
        table_groups=[
            _mapping_group_for(header, ["date", "card_label", "merchant", "extra", "transaction_type", "amount"])
        ],
        option_labels={},
        applied_profiles=[],
    )
    normalization_output = build_transactions(
        merge_output=merge_output,
        mapping_output=mapping_output,
        merged_dir=merged_dir,
    )
    assert normalization_output is not None
    assert normalization_output.transaction_count == 1
    assert normalization_output.amount_total == 10300
    assert normalization_output.summary["normalized_duplicate_excluded_count"] == 1


def _assert_hyundai_combined_header_row_repaired(root: Path) -> None:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    output_dir.mkdir(parents=True)
    header = [
        "이용일 이용카드",
        "이용가맹점",
        "이용금액",
        "할부/회차",
        "적립/할인율(%)",
        "예상적립/할인",
        "결제원금",
        "결제 후 잔액",
        "수수료(이자)",
    ]
    cells = ["04.28", "본인 the Purple(KAL)", "한국정보통신 - 파이브가이즈", "26,300", "", "0.1", "26", "26,300", "", ""]
    merge_output = build_row_outputs(
        vision_results=[_vision_with_header("page_007_chunk_03", header, [cells], page_number=7)],
        chunks=[_chunk("page_007_chunk_03", root / "chunk_03.png", 3, page_number=7)],
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    mapping_output = MappingOutput(
        suggestions_path=merged_dir / "mapping_suggestions.json",
        profile_dir=root / "profiles",
        table_groups=[
            _mapping_group_for(
                header,
                ["date", "card_label", "merchant", "amount", "extra", "discount", "points", "billing_amount", "extra", "extra"],
            )
        ],
        option_labels={},
        applied_profiles=[],
    )
    normalization_output = build_transactions(
        merge_output=merge_output,
        mapping_output=mapping_output,
        merged_dir=merged_dir,
    )
    assert normalization_output is not None
    assert normalization_output.transaction_count == 1
    assert normalization_output.amount_total == 26300
    rows = _read_jsonl(normalization_output.transactions_path)
    assert rows[0]["source"]["page"] == 7
    assert rows[0]["transaction"]["card_label"] == "본인 the Purple(KAL)"
    assert rows[0]["transaction"]["merchant"] == "한국정보통신 - 파이브가이즈"


def _assert_hyundai_billing_amount_repaired_from_header(root: Path) -> None:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    output_dir.mkdir(parents=True)
    header = [
        "이용일",
        "이용카드",
        "이용가맹점",
        "이용금액",
        "할부/회차",
        "적립/할인율(%)",
        "예상적립/할인",
        "결제원금",
        "결제 후 잔액",
        "수수료(이자)",
    ]
    cells = ["01.17", "본인 ZERO 포인트형", "GSTHEFRESH춘천한숲시티점", "30,790", "", "1.0", "300", "28,790", "", ""]
    foreign_header = ["이용일", "이용카드", "이용가맹점", "국가", "해외이용금액", "접수금액", "환율", "해외이용수수료", "결제원금(원)"]
    foreign_cells = ["01.11", "the Purple(KAL)", "www.aliexpress.com", "영국", "USD 30.67", "USD 31.01", "1,478.10", "81", "45,835"]
    merge_output = build_row_outputs(
        vision_results=[
            _vision_with_header("page_001_chunk_01", header, [cells], page_number=1),
            _vision_with_header("page_001_chunk_02", foreign_header, [foreign_cells], page_number=1),
        ],
        chunks=[
            _chunk("page_001_chunk_01", root / "chunk_01.png", 1, page_number=1),
            _chunk("page_001_chunk_02", root / "chunk_02.png", 2, page_number=1),
        ],
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    mapping_output = MappingOutput(
        suggestions_path=merged_dir / "mapping_suggestions.json",
        profile_dir=root / "profiles",
        table_groups=[
            _mapping_group_for(
                header,
                ["date", "card_label", "merchant", "amount", "extra", "discount", "points", "extra", "extra", "extra"],
            ),
            _mapping_group_for(
                foreign_header,
                ["date", "card_label", "merchant", "extra", "extra", "extra", "extra", "extra", "billing_amount"],
            ),
        ],
        option_labels={},
        applied_profiles=[],
    )
    normalization_output = build_transactions(
        merge_output=merge_output,
        mapping_output=mapping_output,
        merged_dir=merged_dir,
    )
    assert normalization_output is not None
    assert normalization_output.transaction_count == 2
    assert normalization_output.amount_total == 30790
    assert normalization_output.billing_amount_total == 28790
    rows = _read_jsonl(normalization_output.transactions_path)
    assert rows[0]["transaction"]["billing_amount"] == 28790
    assert rows[1]["transaction"]["billing_amount"] == 45835


def _assert_hyundai_split_content_row_repaired(root: Path) -> None:
    output_dir = root / "output"
    merged_dir = output_dir / "merged"
    output_dir.mkdir(parents=True)
    header = ["이용일", "이용내용", "이용금액", "적립율", "적립포인트", "청구금액"]
    cells = ["01.29", "본인 the Purple(KAL)", "AMAZON MKTPL*J500060 USD:58.98", "86,640", "0.1", "86", "86,640"]
    merge_output = build_row_outputs(
        vision_results=[_vision_with_header("page_002_chunk_01", header, [cells], page_number=2)],
        chunks=[_chunk("page_002_chunk_01", root / "chunk_01.png", 1, page_number=2)],
        input_pdf=root / "sample.pdf",
        output_dir=output_dir,
        merged_dir=merged_dir,
    )
    mapping_output = MappingOutput(
        suggestions_path=merged_dir / "mapping_suggestions.json",
        profile_dir=root / "profiles",
        table_groups=[
            _mapping_group_for(
                header,
                ["date", "card_label", "amount", "points", "billing_amount", "extra"],
            )
        ],
        option_labels={},
        applied_profiles=[],
    )
    normalization_output = build_transactions(
        merge_output=merge_output,
        mapping_output=mapping_output,
        merged_dir=merged_dir,
    )
    assert normalization_output is not None
    assert normalization_output.amount_total == 86640
    assert normalization_output.billing_amount_total == 86640
    rows = _read_jsonl(normalization_output.transactions_path)
    assert rows[0]["transaction"]["merchant"] == "AMAZON MKTPL*J500060 USD:58.98"


def _vision_with_header(
    chunk_id: str,
    header: list[str],
    cells_list: list[list[str]],
    page_number: int = 1,
    review_reasons: list[str] | None = None,
) -> VisionResult:
    result = _vision(chunk_id, cells_list)
    result = VisionResult(
        chunk_id=result.chunk_id,
        page_number=page_number,
        cache_path=result.cache_path,
        status=result.status,
        data=result.data,
        error_path=result.error_path,
        raw_text_path=result.raw_text_path,
        reused=result.reused,
    )
    assert result.data is not None
    result.data["header"] = header
    result.data["page"] = page_number
    if review_reasons:
        for row, reason in zip(result.data.get("rows", []), review_reasons):
            row["needs_review"] = bool(reason)
            row["review_reason"] = reason
    return result


def _mapping_group_for(header: list[str], fields: list[str]) -> dict[str, object]:
    return {
        "group_id": "|".join(header),
        "row_count": 1,
        "header": header,
        "columns": [
            {
                "column_index": index,
                "column_id": f"col_{index + 1}",
                "header": label,
                "suggested_field": fields[index],
                "selected_field": fields[index],
                "requires_review": False,
            }
            for index, label in enumerate(header)
        ],
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


if __name__ == "__main__":
    raise SystemExit(main())
