from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from src.chunk_builder import build_total_chunks
from src.page_renderer import PageImage
from src.validator import build_validation
from src.normalizer import NormalizationOutput
from src.vision_extractor import VisionResult


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        page_path = root / "page_001.png"
        image = Image.new("RGB", (400, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.text((20, 720), "이번달 결제금액 30,000", fill="black")
        image.save(page_path)

        pages = [
            PageImage(
                page_number=1,
                image_path=page_path,
                width=400,
                height=800,
                dpi=300,
                reused=False,
            )
        ]
        chunks = build_total_chunks(
            pages=pages,
            chunks_dir=root / "total_chunks",
            config={
                "header_ratio": 0.1,
                "summary_start_ratio": 0.7,
                "summary_end_ratio": 1.0,
                "attach_header": True,
            },
        )
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "page_001_totals_01"
        assert chunks[0].image_path.exists()
        manifest = json.loads((root / "total_chunks" / "total_chunks_manifest.json").read_text(encoding="utf-8"))
        assert manifest[0]["chunk_id"] == "page_001_totals_01"

        merged_dir = root / "merged"
        merged_dir.mkdir()
        transactions_path = merged_dir / "transactions.jsonl"
        transactions_path.write_text(json.dumps(_transaction(30000), ensure_ascii=False) + "\n", encoding="utf-8")
        summary_path = merged_dir / "normalization_summary.json"
        summary_path.write_text("{}", encoding="utf-8")
        validation = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=transactions_path,
                summary_path=summary_path,
                transaction_count=1,
                review_count=0,
                amount_total=30000,
                billing_amount_total=0,
                summary={},
            ),
            vision_results=[_total_result()],
            merged_dir=merged_dir,
            expected_chunk_count=1,
        )
        assert validation is not None
        candidates = validation.summary["checksum"]["source_total_candidates"]
        assert candidates[0]["chunk_id"] == "page_001_totals_01"
        assert candidates[0]["amount"] == 30000

        filtered = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=transactions_path,
                summary_path=summary_path,
                transaction_count=1,
                review_count=0,
                amount_total=30000,
                billing_amount_total=0,
                summary={},
            ),
            vision_results=[_point_usage_result()],
            merged_dir=merged_dir,
            expected_chunk_count=1,
        )
        assert filtered is not None
        assert filtered.summary["checksum"]["status"] == "no_source_total"
        assert filtered.summary["checksum"]["source_total_candidates"] == []

    print("total chunks test passed")
    return 0


def _transaction(amount: int) -> dict[str, object]:
    return {
        "source": {"page": 1, "chunk_id": "page_001_chunk_01", "local_row_index": 1},
        "raw": {"header": ["date", "merchant", "amount"], "cells": ["03.14", "store", str(amount)]},
        "transaction": {
            "date": "03.14",
            "card_label": "card",
            "merchant": "store",
            "amount": amount,
            "billing_amount": None,
            "transaction_type": "",
        },
        "quality": {"needs_review": False, "review_reason": ""},
        "extra_fields": {},
    }


def _total_result() -> VisionResult:
    return VisionResult(
        chunk_id="page_001_totals_01",
        page_number=1,
        cache_path=Path("page_001_totals_01.vision.json"),
        status="cached",
        data={
            "schema_version": "1.0",
            "page": 1,
            "chunk_id": "page_001_totals_01",
            "header": [],
            "rows": [],
            "totals": [
                {
                    "label": "이번달 결제금액",
                    "value_text": "30,000",
                    "amount": 30000,
                    "needs_review": False,
                    "review_reason": "",
                }
            ],
            "needs_review": False,
            "review_reason": "",
            "notes": "",
        },
        reused=True,
    )


def _point_usage_result() -> VisionResult:
    return VisionResult(
        chunk_id="page_001_totals_01",
        page_number=1,
        cache_path=Path("page_001_totals_01.vision.json"),
        status="cached",
        data={
            "schema_version": "1.0",
            "page": 1,
            "chunk_id": "page_001_totals_01",
            "header": [],
            "rows": [],
            "totals": [
                {
                    "label": "이마트(노브랜드등) M포인트사용 01.27",
                    "value_text": "-2,000",
                    "amount": -2000,
                    "needs_review": False,
                    "review_reason": "",
                }
            ],
            "needs_review": False,
            "review_reason": "",
            "notes": "The document shows transaction-level point deductions rather than a grand summary total.",
        },
        reused=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
