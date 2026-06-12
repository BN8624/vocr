from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.normalizer import NormalizationOutput
from src.validator import build_validation


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        merged_dir = root / "merged"
        merged_dir.mkdir()
        transactions_path = merged_dir / "transactions.jsonl"
        summary_path = merged_dir / "normalization_summary.json"

        rows = [
            _transaction("not-date", f"가맹점처럼긴카드명{i}", "12345", None, ["x", "card", "12345", ""])
            for i in range(6)
        ]
        rows.append(_transaction("03.14", "the Purple", "쿠팡", 10000, ["03.14", "the Purple", "쿠팡", "10000"]))
        _write_jsonl(transactions_path, rows)
        summary_path.write_text("{}", encoding="utf-8")

        output = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=transactions_path,
                summary_path=summary_path,
                transaction_count=len(rows),
                review_count=0,
                amount_total=10000,
                billing_amount_total=0,
                summary={},
            ),
            vision_results=[],
            merged_dir=merged_dir,
            expected_chunk_count=0,
        )

        assert output is not None
        quality = output.summary["column_quality"]
        codes = {issue["code"] for issue in quality["issues"]}
        assert "date_parse_success_rate_low" in codes
        assert "amount_parse_success_rate_low" in codes
        assert "merchant_numeric_like_rate_high" in codes
        assert "card_label_column_contaminated" in codes
        assert quality["issue_count"] >= 4

    print("column quality test passed")
    return 0


def _transaction(
    date: str,
    card_label: str,
    merchant: str,
    amount: int | None,
    cells: list[str],
) -> dict[str, object]:
    return {
        "source": {"page": 1, "chunk_id": "page_001_chunk_01", "local_row_index": 1},
        "raw": {"header": ["date", "card", "merchant", "amount"], "cells": cells},
        "transaction": {
            "date": date,
            "card_label": card_label,
            "merchant": merchant,
            "amount": amount,
            "billing_amount": None,
            "transaction_type": "",
        },
        "quality": {"needs_review": False, "review_reason": ""},
        "extra_fields": {},
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
