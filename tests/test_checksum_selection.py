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
        validated_rows = _read_jsonl(first.validated_transactions_path)
        assert validated_rows[0]["automation"]["row_status"] == "auto_confirmed"
        assert validated_rows[0]["automation"]["risk_level"] == "low"
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

        multi_page = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=transactions_path,
                summary_path=summary_path,
                transaction_count=1,
                review_count=0,
                amount_total=300000,
                billing_amount_total=0,
                summary={},
            ),
            vision_results=[
                _vision_total("총합계", 100000, page_number=1, chunk_id="page_001_chunk_03"),
                _vision_total("총합계", 200000, page_number=2, chunk_id="page_002_chunk_03"),
            ],
            merged_dir=merged_dir,
            expected_chunk_count=2,
        )
        assert multi_page is not None
        assert multi_page.checksum_status == "auto_selected_total_matched"
        assert multi_page.summary["checksum"]["matched_total"]["label"] == "총합계 합산"
        assert multi_page.summary["checksum"]["matched_total"]["pages"] == [1, 2]
        assert multi_page.summary["checksum"]["matched_field"] == "amount_total"

        samsung_transactions_path = merged_dir / "samsung_transactions.jsonl"
        samsung_rows = [
            _transaction(
                9950,
                source_file="삼성카드_테스트.pdf",
                cells=["01-01", "본인 301", "가맹점A", "10,000", "", "", "9,950", "", "", "청구할인", "-50"],
                extra_fields={"이용금액": "10,000", "discount": ["청구할인", "-50"]},
            ),
            _transaction(
                19900,
                source_file="삼성카드_테스트.pdf",
                cells=["01-02", "본인 301", "가맹점B", "20,000", "", "", "19,900", "", "", "청구할인", "-100"],
                extra_fields={"이용금액": "20,000", "discount": ["청구할인", "-100"]},
            ),
        ]
        _write_jsonl(samsung_transactions_path, samsung_rows)
        samsung = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=samsung_transactions_path,
                summary_path=summary_path,
                transaction_count=2,
                review_count=0,
                amount_total=29850,
                billing_amount_total=0,
                summary={},
            ),
            vision_results=[
                _vision_total("이용금액합계", 10000, page_number=1, chunk_id="page_001_chunk_01"),
                _vision_total("이용금액합계", 20000, page_number=2, chunk_id="page_002_chunk_01"),
            ],
            merged_dir=merged_dir,
            expected_chunk_count=2,
        )
        assert samsung is not None
        assert samsung.checksum_status == "auto_selected_total_matched"
        assert samsung.summary["checksum"]["matched_total"]["label"] in {
            "이용금액합계 합산",
            "삼성 이용금액합계 합산",
        }
        assert samsung.summary["checksum"]["matched_field"] == "samsung_usage_amount_total"
        assert samsung.summary["checksum"]["basis_totals"] == [
            {"field": "samsung_usage_amount_total", "label": "삼성 거래 이용금액 합계", "amount": 30000}
        ]

        kb = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=transactions_path,
                summary_path=summary_path,
                transaction_count=1,
                review_count=0,
                amount_total=300000,
                billing_amount_total=300000,
                summary={},
            ),
            vision_results=[
                _vision_total("김*호 이번달 결제금액", 100000, page_number=1, chunk_id="page_001_totals_01"),
                _vision_total("합계 12 건", 200000, page_number=2, chunk_id="page_002_chunk_01"),
                _vision_total("합계 적립예정 포인트리", 999, page_number=2, chunk_id="page_002_chunk_01"),
            ],
            merged_dir=merged_dir,
            expected_chunk_count=3,
        )
        assert kb is not None
        assert kb.checksum_status == "auto_selected_total_matched"
        assert kb.summary["checksum"]["matched_total"]["label"] == "KB 페이지별 이번달 결제금액 합산"
        assert kb.summary["checksum"]["matched_total"]["pages"] == [1, 2]
        assert kb.summary["checksum"]["matched_field"] == "amount_total"

        revolving = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=transactions_path,
                summary_path=summary_path,
                transaction_count=1,
                review_count=0,
                amount_total=999999,
                billing_amount_total=250000,
                summary={},
            ),
            vision_results=[
                _vision_total("일부결제금액이월약정 소계", 100000, page_number=1, chunk_id="page_001_chunk_03"),
                _vision_total("총 합계", 100000, page_number=1, chunk_id="page_001_chunk_03"),
                _vision_total("일부결제금액이월약정 소계", 200000, page_number=2, chunk_id="page_002_chunk_03"),
                _vision_total("총 합계", 200000, page_number=2, chunk_id="page_002_chunk_03"),
            ],
            merged_dir=merged_dir,
            expected_chunk_count=2,
        )
        assert revolving is not None
        # 리볼빙 명세서: 원본 총합계(이월분 포함)가 결제원금 합보다 크면 이월분을 무시하고 일치 처리
        assert revolving.checksum_status == "auto_selected_total_matched"
        assert revolving.summary["checksum"]["matched_field"] == "billing_amount_total_revolving_carryover"
        assert revolving.summary["checksum"]["matched_total"]["amount"] == 300000
        assert revolving.summary["checksum"]["auto_match_candidates"][0]["carryover_total"] == 50000

        # 결제원금 합이 원본 총합계를 초과(과추출)하면 리볼빙으로도 일치시키지 않는다
        over_extracted = build_validation(
            normalization_output=NormalizationOutput(
                transactions_path=transactions_path,
                summary_path=summary_path,
                transaction_count=1,
                review_count=0,
                amount_total=999999,
                billing_amount_total=350000,
                summary={},
            ),
            vision_results=[
                _vision_total("일부결제금액이월약정 소계", 100000, page_number=1, chunk_id="page_001_chunk_03"),
                _vision_total("총 합계", 100000, page_number=1, chunk_id="page_001_chunk_03"),
                _vision_total("일부결제금액이월약정 소계", 200000, page_number=2, chunk_id="page_002_chunk_03"),
                _vision_total("총 합계", 200000, page_number=2, chunk_id="page_002_chunk_03"),
            ],
            merged_dir=merged_dir,
            expected_chunk_count=2,
        )
        assert over_extracted is not None
        assert over_extracted.checksum_status != "auto_selected_total_matched"

    print("checksum selection test passed")
    return 0


def _transaction(
    amount: int,
    source_file: str = "",
    cells: list[str] | None = None,
    extra_fields: dict[str, object] | None = None,
) -> dict[str, object]:
    row_cells = cells or ["03.14", "store", str(amount)]
    return {
        "source": {
            "file": source_file,
            "page": 1,
            "chunk_id": "page_001_chunk_01",
            "local_row_index": 1,
        },
        "raw": {"header": ["date", "merchant", "amount"], "cells": row_cells},
        "transaction": {
            "date": row_cells[0],
            "card_label": "card",
            "merchant": "store",
            "amount": amount,
            "billing_amount": None,
            "transaction_type": "",
        },
        "quality": {"needs_review": False, "review_reason": ""},
        "extra_fields": extra_fields or {},
    }


def _vision_total(
    label: str,
    amount: int,
    page_number: int = 1,
    chunk_id: str = "page_001_chunk_01",
) -> VisionResult:
    return VisionResult(
        chunk_id=chunk_id,
        page_number=page_number,
        cache_path=Path(f"{chunk_id}.vision.json"),
        status="cached",
        data={
            "schema_version": "1.0",
            "page": page_number,
            "chunk_id": chunk_id,
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


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
