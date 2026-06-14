# convert.py 실사용 진입점의 대상 선택과 명령 생성을 검증한다.
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import convert


def main() -> int:
    repo_root = Path.cwd()
    args = argparse.Namespace(
        input="견본",
        output_root="output/converted_test",
        output="",
        config="config.yaml",
        mode="page",
        model="",
        dry_run=True,
        force=False,
        force_vision=False,
        continue_on_error=False,
    )
    targets = convert.build_targets(repo_root, args)
    assert targets
    assert all(target.pdf_path.suffix.lower() == ".pdf" for target in targets)
    assert all(target.output_dir.parent == (repo_root / "output" / "converted_test").resolve() for target in targets)

    pdf_target = next(target for target in targets if target.pdf_path.name == "현대카드_8.pdf")
    assert pdf_target.output_dir.name == "현대카드_8"

    single_args = argparse.Namespace(**{**vars(args), "input": "견본/현대카드_8.pdf", "output": "output/single_convert"})
    single = convert.build_targets(repo_root, single_args)
    assert len(single) == 1
    assert single[0].output_dir == (repo_root / "output" / "single_convert").resolve()

    print("convert entrypoint test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
