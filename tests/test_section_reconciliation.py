# 섹션별 검산 리포트 생성을 검증한다.
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.normalizer import NormalizationOutput
from src.reconciliation import write_section_reconciliation
from src.validator import build_validation


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        merged_dir = root / "merged"
        merged_dir.mkdir()
        transactions_path = merged_dir / "transactions.jsonl"
        rows_merged_path = merged_dir / "rows_merged.jsonl"
        rows = [
            _row(page=1, amount=1000, merchant="store"),
            _row(page=2, amount=0, merchant="foreign detail", header=["이용일", "국가", "해외이용금액", "결제원금(원)"], billing_amount=1000),
            _row(page=2, amount=0, merchant="M포인트", header=["이용일", "종류", "이용포인트/캐시백/마일리지"]),
        ]
        _write_jsonl(transactions_path, rows)
        _write_jsonl(rows_merged_path, [
            _raw_row(page=1, cells=["01.01", "본인", "M포인트 사용", "-1,000"]),
            _raw_row(page=1, cells=["01.01", "본인", "M포인트 사용", "-1,000"]),
        ])
        summary_path = merged_dir / "normalization_summary.json"
        summary_path.write_text(json.dumps({"amount_total": 1000, "billing_amount_total": 1000}, ensure_ascii=False), encoding="utf-8")
        normalization = NormalizationOutput(
            transactions_path=transactions_path,
            summary_path=summary_path,
            transaction_count=len(rows),
            review_count=0,
            amount_total=1000,
            billing_amount_total=1000,
            summary={},
        )
        validation = build_validation(
            normalization_output=normalization,
            vision_results=[],
            merged_dir=merged_dir,
            expected_chunk_count=1,
            review_state={},
        )
        validation.summary["checksum"]["source_total_candidates"] = [
            {"id": "t1", "label": "총 합계", "amount": 1000, "page": 2, "chunk_id": "page_002_chunk_01"}
        ]
        validation.summary_path.write_text(json.dumps(validation.summary, ensure_ascii=False), encoding="utf-8")
        path = write_section_reconciliation(validation, merged_dir)
        assert path == merged_dir / "section_reconciliation.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["pair_count"] == 1
        pair = report["pairs"][0]
        assert pair["pages"] == [1, 2]
        assert pair["section_totals"]["billing_detail"]["amount_total"] == 1000
        assert pair["section_totals"]["foreign_detail"]["billing_amount_total"] == 1000
        assert pair["raw_adjustment_totals"]["raw_benefit_dated"]["row_count"] == 2
        assert pair["raw_adjustment_totals"]["raw_benefit_dated"]["unique_row_count"] == 1
        assert pair["raw_adjustment_totals"]["raw_benefit_dated"]["unique_amount_total"] == -1000
        assert pair["explanation"]["status"] == "matched"

    print("section reconciliation test passed")
    return 0


def _row(page: int, amount: int, merchant: str, header: list[str] | None = None, billing_amount: int | None = None) -> dict[str, object]:
    return {
        "source": {"file": "현대카드_8.pdf", "page": page, "chunk_id": f"page_{page:03d}_chunk_01", "local_row_index": 1},
        "raw": {"header": header or ["이용일", "이용카드", "이용가맹점", "이용금액"], "cells": []},
        "transaction": {
            "date": "01-01",
            "card_label": "본인",
            "merchant": merchant,
            "amount": amount,
            "billing_amount": billing_amount,
            "transaction_type": "",
        },
        "quality": {"needs_review": False, "review_reason": ""},
        "extra_fields": {},
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _raw_row(page: int, cells: list[str]) -> dict[str, object]:
    return {
        "source": {"file": "현대카드_8.pdf", "page": page, "chunk_id": f"page_{page:03d}_chunk_01", "local_row_index": 2},
        "raw": {"header": ["이용일", "이용카드", "이용가맹점", "이용금액"], "cells": cells},
        "merge": {"decision": "duplicate_excluded"},
    }


if __name__ == "__main__":
    raise SystemExit(main())
