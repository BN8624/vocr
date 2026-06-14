from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.automation import write_automation_summary
from src.normalizer import NormalizationOutput
from src.validator import ValidationOutput


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        merged_dir = root / "merged"
        merged_dir.mkdir()
        rows_path = merged_dir / "transactions_validated.jsonl"
        rows = [
            _row("auto_confirmed"),
            _row("auto_confirmed"),
            _row("needs_light_review"),
            _row("needs_hard_review"),
        ]
        with rows_path.open("w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

        validation_output = ValidationOutput(
            validated_transactions_path=rows_path,
            issues_path=merged_dir / "validation_issues.json",
            summary_path=merged_dir / "validation_summary.json",
            transaction_count=4,
            row_issue_count=1,
            issue_row_count=1,
            checksum_status="auto_selected_total_matched",
            checksum_difference=0,
            summary={"checksum": {"status": "auto_selected_total_matched"}},
        )
        normalization_output = NormalizationOutput(
            transactions_path=merged_dir / "transactions.jsonl",
            summary_path=merged_dir / "normalization_summary.json",
            transaction_count=4,
            review_count=1,
            amount_total=100,
            billing_amount_total=0,
            summary={},
        )

        summary_path = write_automation_summary(validation_output, normalization_output, merged_dir)
        assert summary_path == merged_dir / "automation_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["transaction_count"] == 4
        assert summary["auto_accept_count"] == 2
        assert summary["manual_review_count"] == 2
        assert summary["hard_review_count"] == 1
        assert summary["manual_review_rate"] == 0.5
        assert summary["checksum"]["source"] == "auto_selected"
        assert summary["checksum_review_required"] is False

    print("automation summary test passed")
    return 0


def _row(status: str) -> dict[str, object]:
    return {
        "transaction": {"amount": 1},
        "automation": {
            "row_status": status,
            "confidence_score": 0.9,
            "risk_level": "low",
            "signals": {},
            "reasons": [],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
