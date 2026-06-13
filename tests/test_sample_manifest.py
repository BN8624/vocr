from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.regression_samples import sample_issuer
from tools.build_sample_manifest import build_manifest, parse_sample_name, sample_type


def main() -> int:
    parsed = parse_sample_name(Path("현대카드_1.pdf"))
    assert parsed["sample_id"] == "현대카드_1"
    assert parsed["issuer"] == "현대카드"
    assert parsed["expected_pages"] == 1
    assert sample_type(1) == "single_page"
    assert sample_type(2) == "two_pages"
    assert sample_type(3) == "three_pages"
    assert sample_type(8) == "multi_page"
    assert sample_issuer(Path("신한카드_11.pdf")) == "신한카드"

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        for name in ["삼성카드_1.pdf", "삼성카드_2.pdf", "현대카드_8.pdf"]:
            (root / name).write_bytes(b"%PDF-1.4\n")
        manifest = build_manifest(root)
        assert [row["sample_id"] for row in manifest] == ["삼성카드_1", "삼성카드_2", "현대카드_8"]
        assert [row["sample_type"] for row in manifest] == ["single_page", "two_pages", "multi_page"]

    print("sample manifest test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
