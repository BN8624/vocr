from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunk_builder import ChunkImage
from src.page_renderer import PageImage
from src.review_builder import build_review_html


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        page_path = root / "page_001.png"
        chunk_path = root / "page_001_chunk_01.png"
        _write_blank(page_path)
        _write_blank(chunk_path)

        review_path = build_review_html(
            output_dir=root,
            pages=[
                PageImage(
                    page_number=1,
                    image_path=page_path,
                    width=120,
                    height=160,
                    dpi=100,
                    reused=False,
                )
            ],
            chunks=[
                ChunkImage(
                    chunk_id="page_001_chunk_01",
                    page_number=1,
                    chunk_index=1,
                    image_path=chunk_path,
                    width=120,
                    height=80,
                    source_y_start=20,
                    source_y_end=120,
                    header_y_start=0,
                    header_y_end=16,
                    reused=False,
                )
            ],
            config={"html_title": "Smoke Review"},
            input_pdf=root / "sample.pdf",
        )
        html = review_path.read_text(encoding="utf-8")
        assert "<title>Smoke Review</title>" in html
        assert "<style>" in html
        assert "<script>" in html
        assert "const saveButton = document.getElementById('save-mapping')" in html
        assert "data-overlay-field=\"body_start_ratio\"" in html
        assert "이 페이지 자르기 조정" in html
        assert "page_001_chunk_01" in html
        assert "{{ body }}" not in html
        assert "{{ script_block }}" not in html

    print("review html smoke test passed")
    return 0


def _write_blank(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for this test") from exc
    Image.new("RGB", (120, 160), "white").save(path)


if __name__ == "__main__":
    raise SystemExit(main())
