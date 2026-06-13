from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.normalizer import NormalizationOutput
from src.validator import build_validation
from src.vision_extractor import VisionResult


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        merged_dir = root / "merged"
        merged_dir.mkdir()
        transactions_path = merged_dir / "transactions.jsonl"
        summary_path = merged_dir / "normalization_summary.json"
        _write_jsonl(transactions_path, [_transaction(10000)])
        summary_path.write_text("{}", encoding="utf-8")

        normalization_output = NormalizationOutput(
            transactions_path=transactions_path,
            summary_path=summary_path,
            transaction_count=1,
            review_count=0,
            amount_total=10000,
            billing_amount_total=0,
            summary={},
        )
        vision_results = [_vision_total("이번달 결제금액", 10000)]

        first = build_validation(
            normalization_output=normalization_output,
            vision_results=vision_results,
            merged_dir=merged_dir,
            expected_chunk_count=1,
        )
        assert first is not None
        assert first.checksum_status == "auto_selected_total_matched"
        auto_matches = first.summary["checksum"]["auto_match_candidates"]
        assert len(auto_matches) == 1

        selected_total_id = first.summary["checksum"]["source_total_candidates"][0]["id"]
        confirmed = build_validation(
            normalization_output=normalization_output,
            vision_results=vision_results,
            merged_dir=merged_dir,
            expected_chunk_count=1,
            review_state={"checksum": {"selected_total_id": selected_total_id}},
        )
        assert confirmed is not None
        assert confirmed.checksum_status == "user_confirmed_total_matched"
        assert confirmed.checksum_difference == 0

        mismatch_preview = build_validation(
            normalization_output=normalization_output,
            vision_results=[_vision_total("이번달 결제금액", 12000)],
            merged_dir=merged_dir,
            expected_chunk_count=1,
        )
        assert mismatch_preview is not None
        mismatch_total_id = mismatch_preview.summary["checksum"]["source_total_candidates"][0]["id"]
        mismatch = build_validation(
            normalization_output=normalization_output,
            vision_results=[_vision_total("이번달 결제금액", 12000)],
            merged_dir=merged_dir,
            expected_chunk_count=1,
            review_state={"checksum": {"selected_total_id": mismatch_total_id}},
        )
        assert mismatch is not None
        assert mismatch.checksum_status == "user_confirmed_total_mismatch"
        assert mismatch.checksum_difference == -2000

        adjusted = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=transactions_path,
                summary_path=summary_path,
                transaction_count=1,
                review_count=0,
                amount_total=118000,
                billing_amount_total=0,
                summary={},
            ),
            vision_results=[
                _vision_total("\uccad\uad6c\ud560\uc778 \uc18c\uacc4", -18000),
                _vision_total("\ucd1d\ud569\uacc4", 100000),
                _vision_total("\uc77c\ubd80\uacb0\uc81c\uae08\uc561\uc774\uc6d4\uc57d\uc815 \uc18c\uacc4", 100000),
            ],
            merged_dir=merged_dir,
            expected_chunk_count=1,
        )
        assert adjusted is not None
        assert adjusted.checksum_status == "auto_selected_total_matched"
        assert adjusted.summary["checksum"]["matched_total"]["label"] == "총합계"
        assert adjusted.summary["checksum"]["matched_field"] == "amount_total_adjusted"

    print("checksum selection test passed")
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


def _vision_total(label: str, amount: int) -> VisionResult:
    return VisionResult(
        chunk_id="page_001_chunk_01",
        page_number=1,
        cache_path=Path("page_001_chunk_01.vision.json"),
        status="cached",
        data={
            "schema_version": "1.0",
            "page": 1,
            "chunk_id": "page_001_chunk_01",
            "header": [],
            "rows": [],
            "totals": [
                {
                    "label": label,
                    "value_text": f"{amount:,}",
                    "amount": amount,
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


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
