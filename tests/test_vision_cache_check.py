from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_vision_cache import check_cache


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        output_dir = root / "sample"
        (output_dir / "chunks").mkdir(parents=True)
        (output_dir / "total_chunks").mkdir(parents=True)
        (output_dir / "cache").mkdir(parents=True)

        _write_json(
            output_dir / "chunks" / "chunks_manifest.json",
            [{"chunk_id": "page_001_chunk_01"}, {"chunk_id": "page_001_chunk_02"}],
        )
        _write_json(
            output_dir / "total_chunks" / "total_chunks_manifest.json",
            [{"chunk_id": "page_001_totals_01"}],
        )
        _write_json(output_dir / "cache" / "page_001_chunk_01.vision.json", {"rows": []})
        _write_json(output_dir / "cache" / "page_001_chunk_02.vision.error.json", {"status": "error"})

        report = check_cache(output_dir)
        assert report.expected_chunk_count == 3
        assert report.cached_count == 1
        assert report.error_chunk_ids == ["page_001_chunk_02"]
        assert report.missing_chunk_ids == ["page_001_totals_01"]
        assert not report.ready

        _write_json(output_dir / "cache" / "page_001_chunk_02.vision.json", {"rows": []})
        _write_json(output_dir / "cache" / "page_001_totals_01.vision.json", {"totals": []})
        (output_dir / "cache" / "page_001_chunk_02.vision.error.json").unlink()

        ready_report = check_cache(output_dir)
        assert ready_report.expected_chunk_count == 3
        assert ready_report.cached_count == 3
        assert ready_report.error_chunk_ids == []
        assert ready_report.missing_chunk_ids == []
        assert ready_report.ready

    print("vision cache check test passed")
    return 0


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
