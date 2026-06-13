from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.normalizer import NormalizationOutput
from src.validator import build_validation


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        clean = _run_fixture(root, temp_root / "clean", "validation_clean.jsonl")
        assert clean is not None
        assert clean.issue_row_count == 0
        assert clean.summary["column_quality"]["issue_count"] == 0

        card_label = _run_rows(temp_root / "card_label", [_transaction("본인 the Purple(KAL)", "정상가맹점", 1000)])
        assert card_label is not None
        assert card_label.issue_row_count == 0

        taxi = _run_rows(temp_root / "taxi", [_transaction("본인 ZERO 포인트형", "택시-서울 33 사 9557", 5100)])
        assert taxi is not None
        assert taxi.issue_row_count == 0

        benefit = _run_rows(temp_root / "benefit", [_benefit_transaction()])
        assert benefit is not None
        assert benefit.issue_row_count == 0

        contaminated = _run_fixture(root, temp_root / "contaminated", "validation_contaminated.jsonl")
        assert contaminated is not None
        assert contaminated.issue_row_count == 5
        row_codes = {
            issue["code"]
            for sample in contaminated.summary["review_samples"]
            for issue in sample["issues"]
        }
        assert "merchant_mostly_numeric" in row_codes

        column_codes = {
            issue["code"]
            for issue in contaminated.summary["column_quality"]["issues"]
        }
        assert "merchant_numeric_like_rate_high" in column_codes
        assert "card_label_column_contaminated" in column_codes

    print("validation fixtures test passed")
    return 0


def _run_fixture(root: Path, merged_dir: Path, fixture_name: str):
    merged_dir.mkdir(parents=True)
    fixture_path = root / "tests" / "fixtures" / fixture_name
    transactions_path = merged_dir / "transactions.jsonl"
    shutil.copyfile(fixture_path, transactions_path)
    rows = _read_jsonl(transactions_path)
    amount_total = sum(row["transaction"]["amount"] for row in rows)
    billing_total = sum(row["transaction"]["billing_amount"] for row in rows)
    summary_path = merged_dir / "normalization_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "transaction_count": len(rows),
                "review_count": 0,
                "amount_total": amount_total,
                "billing_amount_total": billing_total,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return build_validation(
        normalization_output=NormalizationOutput(
            transactions_path=transactions_path,
            summary_path=summary_path,
            transaction_count=len(rows),
            review_count=0,
            amount_total=amount_total,
            billing_amount_total=billing_total,
            summary={},
        ),
        vision_results=[],
        merged_dir=merged_dir,
        expected_chunk_count=0,
    )


def _run_rows(merged_dir: Path, rows: list[dict[str, object]]):
    merged_dir.mkdir(parents=True)
    transactions_path = merged_dir / "transactions.jsonl"
    with transactions_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    amount_total = sum(
        value
        for row in rows
        if isinstance((value := row["transaction"]["amount"]), int)  # type: ignore[index]
    )
    billing_total = sum(
        value
        for row in rows
        if isinstance((value := row["transaction"]["billing_amount"]), int)  # type: ignore[index]
    )
    summary_path = merged_dir / "normalization_summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    return build_validation(
        normalization_output=NormalizationOutput(
            transactions_path=transactions_path,
            summary_path=summary_path,
            transaction_count=len(rows),
            review_count=0,
            amount_total=amount_total,
            billing_amount_total=billing_total,
            summary={},
        ),
        vision_results=[],
        merged_dir=merged_dir,
        expected_chunk_count=0,
    )


def _transaction(card_label: str, merchant: str, amount: int) -> dict[str, object]:
    return {
        "source": {"page": 1, "chunk_id": "page_001_chunk_01", "local_row_index": 1},
        "raw": {
            "header": ["이용일", "이용카드", "이용가맹점", "이용금액", "결제원금"],
            "cells": ["01.15", card_label, merchant, f"{amount:,}", f"{amount:,}"],
        },
        "transaction": {
            "date": "01-15",
            "card_label": card_label,
            "merchant": merchant,
            "amount": amount,
            "billing_amount": amount,
            "transaction_type": "",
        },
        "quality": {"needs_review": False, "review_reason": ""},
        "extra_fields": {},
    }


def _benefit_transaction() -> dict[str, object]:
    return {
        "source": {"page": 1, "chunk_id": "page_001_chunk_01", "local_row_index": 13},
        "raw": {
            "header": [
                "이용일",
                "이용카드",
                "이용가맹점",
                "이용금액",
                "할부/회차",
                "적립/할인율(%)",
                "예상적립/할인",
                "결제원금",
            ],
            "cells": ["01.17", "본인 ZERO 포인트형", "GS슈퍼마켓M포인트사용", "", "", "", "-2,000", ""],
        },
        "transaction": {
            "date": "01-17",
            "card_label": "본인 ZERO 포인트형",
            "merchant": "GS슈퍼마켓M포인트사용",
            "amount": None,
            "billing_amount": None,
            "transaction_type": "",
        },
        "quality": {"needs_review": False, "review_reason": ""},
        "extra_fields": {"discount": "-2,000"},
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
