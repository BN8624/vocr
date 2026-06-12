from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def expected_page_count(pdf_path: Path) -> int:
    match = re.search(r"_(\d+)$", pdf_path.stem)
    if not match:
        raise ValueError(f"Sample filename must end with _<page_count>: {pdf_path}")
    return int(match.group(1))


def find_sample_pdfs(samples_dir: Path) -> list[Path]:
    if not samples_dir.exists():
        raise FileNotFoundError(f"Sample folder not found: {samples_dir}")
    return sorted(samples_dir.glob("*.pdf"), key=lambda path: path.name)


def run_phase1(root: Path, pdf_path: Path, output_root: Path) -> dict[str, object]:
    output_dir = output_root / pdf_path.stem
    command = [
        sys.executable,
        str(root / "main.py"),
        "--input",
        str(pdf_path),
        "--output",
        str(output_dir),
        "--dry-run",
        "--force",
    ]
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Phase 1 failed for {pdf_path}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary file: {summary_path}")
    return json.loads(summary_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Phase 1 against all sample PDFs and check filename page counts."
    )
    parser.add_argument("--samples-dir", default="견본", help="Folder containing *_N.pdf files.")
    parser.add_argument("--output", default="output/smoke", help="Smoke test output folder.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    samples_dir = (root / args.samples_dir).resolve()
    output_root = (root / args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    for pdf_path in find_sample_pdfs(samples_dir):
        expected = expected_page_count(pdf_path)
        summary = run_phase1(root, pdf_path, output_root)
        actual = int(summary["page_count"])
        status = "OK" if actual == expected else "MISMATCH"
        print(f"{pdf_path.relative_to(root)}\texpected={expected}\tactual={actual}\t{status}")
        if actual != expected:
            failures.append(f"{pdf_path.name}: expected {expected}, got {actual}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
