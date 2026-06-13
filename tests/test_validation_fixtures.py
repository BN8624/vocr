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


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
