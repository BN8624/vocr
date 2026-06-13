from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunk_builder import ChunkImage
from src.page_renderer import PageImage
from src.profile_store import MappingOutput
from src.review_builder import build_review_html


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        page_path = root / "page_001.png"
        chunk_path = root / "page_001_chunk_01.png"
        suggestions_path = root / "merged" / "mapping_suggestions.json"
        suggestions_path.parent.mkdir(parents=True)
        suggestions_path.write_text("{}", encoding="utf-8")
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
            mapping_output=MappingOutput(
                suggestions_path=suggestions_path,
                profile_dir=root / "profiles",
                table_groups=[
                    {
                        "group_id": "table_1",
                        "row_count": 1,
                        "columns": [
                            {
                                "column_id": "col_1",
                                "header": "이용일",
                                "suggested_field": "date",
                                "requires_review": False,
                                "sample_values": ["03.14"],
                            }
                        ],
                    }
                ],
                option_labels={"date": "이용일", "extra": "추가필드", "ignore": "무시"},
                applied_profiles=[],
            ),
        )
        html = review_path.read_text(encoding="utf-8")
        assert "<title>Smoke Review</title>" in html
        assert "<style>" in html
        assert "<script>" in html
        assert "변환 확인" in html
        assert "workflow-panel" in html
        assert "data-workflow-target=\"pages\"" not in html
        assert "const saveButton = document.getElementById('save-mapping')" in html
        assert "activateWorkflowStep" in html
        assert "wizard-actions" in html
        assert "원본 페이지 확인" not in html
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
