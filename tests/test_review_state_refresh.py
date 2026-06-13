from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serve_review import ReviewRequestHandler, ReviewServer
from src.validator import _total_id


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        output_dir = root / "output"
        merged_dir = output_dir / "merged"
        cache_dir = output_dir / "cache"
        merged_dir.mkdir(parents=True)
        cache_dir.mkdir(parents=True)

        _write_jsonl(merged_dir / "transactions.jsonl", [_transaction(10000)])
        (merged_dir / "normalization_summary.json").write_text(
            json.dumps(
                {
                    "transaction_count": 1,
                    "review_count": 0,
                    "amount_total": 10000,
                    "billing_amount_total": 0,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (output_dir / "summary.json").write_text(
            json.dumps({"chunk_count": 1, "checksum_status": "no_user_total_selected"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (cache_dir / "page_001_totals_01.vision.json").write_text(
            json.dumps(_vision_total("이번달 결제금액", 10000), ensure_ascii=False),
            encoding="utf-8",
        )

        server = ReviewServer(("127.0.0.1", 0), ReviewRequestHandler, root, root / "profiles")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            selected_total_id = _total_id("이번달 결제금액", 10000, 1, "page_001_totals_01")
            response = _post_json(
                f"http://127.0.0.1:{server.server_port}/api/review-state",
                {
                    "state_path": "/output/merged/review_state.json",
                    "checksum": {
                        "selected_total_id": selected_total_id,
                        "selected_total": {"label": "이번달 결제금액", "amount": 10000},
                    },
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert response["ok"] is True
        assert response["refresh"]["ok"] is True
        assert response["refresh"]["checksum_status"] == "user_confirmed_total_matched"
        assert (output_dir / "result.xlsx").exists()
        assert response["refresh"]["excel_path"].endswith("result.xlsx")

        validation_summary = json.loads((merged_dir / "validation_summary.json").read_text(encoding="utf-8"))
        assert validation_summary["checksum"]["status"] == "user_confirmed_total_matched"
        run_summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        assert run_summary["checksum_status"] == "user_confirmed_total_matched"
        assert run_summary["excel_path"].endswith("result.xlsx")

        _assert_mapping_save_refreshes_excel(root)

    print("review state refresh test passed")
    return 0


def _assert_mapping_save_refreshes_excel(root: Path) -> None:
    output_dir = root / "mapping_output"
    merged_dir = output_dir / "merged"
    cache_dir = output_dir / "cache"
    profiles_dir = root / "profiles"
    merged_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    profiles_dir.mkdir()

    row = _raw_row(["03.14", "store", "10,000"])
    _write_jsonl(merged_dir / "rows_raw.jsonl", [row])
    _write_jsonl(merged_dir / "rows_merged.jsonl", [row])
    (merged_dir / "merge_summary.json").write_text(
        json.dumps(
            {
                "raw_row_count": 1,
                "merged_row_count": 1,
                "duplicate_group_count": 0,
                "duplicate_row_count": 0,
                "duplicate_groups": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (merged_dir / "mapping_suggestions.json").write_text(
        json.dumps(_mapping_suggestions(), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps({"chunk_count": 1, "checksum_status": "not_run"}, ensure_ascii=False),
        encoding="utf-8",
    )

    server = ReviewServer(("127.0.0.1", 0), ReviewRequestHandler, root, profiles_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _post_json(
            f"http://127.0.0.1:{server.server_port}/api/mapping-profile",
            {
                "schema_version": "1.0",
                "status": "user_confirmed_save_request",
                "mapping_path": "/mapping_output/merged/mapping_suggestions.json",
                "table_groups": [
                    {
                        "group_id": "table_1",
                        "columns": [
                            {"column_id": "col_1", "selected_field": "date"},
                            {"column_id": "col_2", "selected_field": "merchant"},
                            {"column_id": "col_3", "selected_field": "amount"},
                        ],
                    }
                ],
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response["ok"] is True
    assert response["refresh"]["ok"] is True
    assert (output_dir / "result.xlsx").exists()
    transactions = _read_jsonl(merged_dir / "transactions.jsonl")
    assert transactions[0]["transaction"]["merchant"] == "store"
    assert transactions[0]["transaction"]["amount"] == 10000
    suggestions = json.loads((merged_dir / "mapping_suggestions.json").read_text(encoding="utf-8"))
    assert suggestions["status"] == "user_confirmed_applied"
    saved_profile = next(profiles_dir.glob("*.json"))
    saved_payload = json.loads(saved_profile.read_text(encoding="utf-8"))
    assert "mapping_path" not in saved_payload


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


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


def _raw_row(cells: list[str]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "source": {"file": "sample.pdf", "page": 1, "chunk_id": "page_001_chunk_01", "local_row_index": 1},
        "raw": {
            "header": ["이용일", "가맹점", "금액"],
            "cells": cells,
            "line_text": " ".join(cells),
            "image_ref": "chunks/page_001_chunk_01.png",
        },
        "transaction": {},
        "quality": {"needs_review": False, "review_reason": ""},
        "extra_fields": {},
        "merge": {"decision": "keep"},
    }


def _mapping_suggestions() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "suggested",
        "table_groups": [
            {
                "group_id": "table_1",
                "header": ["이용일", "가맹점", "금액"],
                "columns": [
                    {"column_id": "col_1", "column_index": 0, "header": "이용일", "selected_field": "extra"},
                    {"column_id": "col_2", "column_index": 1, "header": "가맹점", "selected_field": "extra"},
                    {"column_id": "col_3", "column_index": 2, "header": "금액", "selected_field": "extra"},
                ],
            }
        ],
        "option_labels": {},
        "applied_profiles": [],
    }


def _vision_total(label: str, amount: int) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "page": 1,
        "chunk_id": "page_001_totals_01",
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
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
