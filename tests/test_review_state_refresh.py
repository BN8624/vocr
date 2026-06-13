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

        validation_summary = json.loads((merged_dir / "validation_summary.json").read_text(encoding="utf-8"))
        assert validation_summary["checksum"]["status"] == "user_confirmed_total_matched"
        run_summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        assert run_summary["checksum_status"] == "user_confirmed_total_matched"

    print("review state refresh test passed")
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
