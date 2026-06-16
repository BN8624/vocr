# app.py GUI의 진행 단계 매핑과 실행 명령 생성을 검증한다.
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


def main() -> int:
    assert app.stage_for_line("Rendering PDF pages...") == "render"
    assert app.stage_for_line("Page-mode extraction: one Vision call per full page.") == "extract"
    assert app.stage_for_line("Collecting raw rows and duplicate candidates...") == "merge"
    assert app.stage_for_line("Building column mapping suggestions...") == "mapping"
    assert app.stage_for_line("Normalizing mapped rows into transactions...") == "normalize"
    assert app.stage_for_line("Validating normalized transactions...") == "validate"
    assert app.stage_for_line("Exporting reviewable Excel workbook...") == "excel"
    assert app.stage_for_line("Building review HTML...") == "review"
    assert app.stage_for_line("Done. Review file: output/review.html") == "done"
    assert app.stage_for_line("unrelated") is None

    repo_root = Path("C:/work/vocr")
    job = app.Job(pdf_path=Path("C:/work/vocr/input.pdf"), output_dir=Path("C:/work/vocr/output/converted/input"))
    command = app.build_command(repo_root, job, dry_run=True, force_vision=True)
    assert "--input" in command
    assert "--output" in command
    assert "--extraction-mode" in command
    assert "page" in command
    assert "--dry-run" in command
    assert "--force-vision" in command
    output_dir = app.user_output_dir(Path("C:/work/vocr/output/converted"), Path("C:/work/vocr/input.pdf"))
    assert output_dir.parent == Path("C:/work/vocr/output/converted")
    assert output_dir.name.startswith("input_")

    print("app gui test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
