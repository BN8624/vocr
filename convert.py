# PDF 명세서를 Excel 산출물로 변환하는 실사용 진입점
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from review import _safe_output_name


DEFAULT_OUTPUT_ROOT = "output/converted"


@dataclass(frozen=True)
class ConversionTarget:
    pdf_path: Path
    output_dir: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one PDF or a folder of PDFs into result.xlsx files."
    )
    parser.add_argument("input", help="PDF file or folder containing PDF files.")
    parser.add_argument(
        "--output-root",
        default=DEFAULT_OUTPUT_ROOT,
        help="Folder where per-PDF output folders are created. Default: output/converted",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output folder for a single PDF. Cannot be used with folder input.",
    )
    parser.add_argument("--config", default="config.yaml", help="YAML config path.")
    parser.add_argument(
        "--mode",
        choices=["page", "chunk"],
        default="page",
        help="Extraction mode. Default: page",
    )
    parser.add_argument("--model", default="", help="Override Vision model.")
    parser.add_argument("--dry-run", action="store_true", help="Reuse cache and skip API calls.")
    parser.add_argument("--force", action="store_true", help="Rebuild rendered pages and chunks.")
    parser.add_argument("--force-vision", action="store_true", help="Call Vision again instead of cache.")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue converting remaining PDFs when one PDF fails.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    targets = build_targets(repo_root, args)
    if not targets:
        print("No PDF files found.", file=sys.stderr)
        return 2

    failures: list[tuple[ConversionTarget, int]] = []
    for index, target in enumerate(targets, start=1):
        print(f"\n[{index}/{len(targets)}] {target.pdf_path}", flush=True)
        exit_code = run_conversion(repo_root, target, args)
        if exit_code != 0:
            failures.append((target, exit_code))
            print(f"FAILED: {target.pdf_path} (exit {exit_code})", file=sys.stderr)
            if not args.continue_on_error:
                return exit_code
            continue
        excel_path = target.output_dir / "result.xlsx"
        review_path = target.output_dir / "review.html"
        if not excel_path.exists():
            if args.dry_run:
                print(
                    "Dry-run requires an existing Vision cache in the output folder. "
                    "Run without --dry-run for a new PDF.",
                    file=sys.stderr,
                )
            print(f"FAILED: result.xlsx was not created: {excel_path}", file=sys.stderr)
            failures.append((target, 1))
            if not args.continue_on_error:
                return 1
            continue
        print(f"Excel:  {excel_path}", flush=True)
        print(f"Review: {review_path}", flush=True)

    if failures:
        print(f"\nCompleted with {len(failures)} failure(s).", file=sys.stderr)
        return 1
    print("\nAll conversions completed.", flush=True)
    return 0


def build_targets(repo_root: Path, args: argparse.Namespace) -> list[ConversionTarget]:
    input_path = Path(args.input).expanduser()
    if not input_path.is_absolute():
        input_path = repo_root / input_path
    input_path = input_path.resolve()

    output_root = Path(args.output_root).expanduser()
    if not output_root.is_absolute():
        output_root = repo_root / output_root
    output_root = output_root.resolve()

    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            return []
        if args.output:
            output_dir = Path(args.output).expanduser()
            if not output_dir.is_absolute():
                output_dir = repo_root / output_dir
            output_dir = output_dir.resolve()
        else:
            output_dir = output_root / _safe_output_name(input_path)
        return [ConversionTarget(pdf_path=input_path, output_dir=output_dir)]

    if args.output:
        raise SystemExit("--output can only be used with a single PDF input.")
    if not input_path.is_dir():
        return []

    return [
        ConversionTarget(pdf_path=pdf_path.resolve(), output_dir=output_root / _safe_output_name(pdf_path))
        for pdf_path in sorted(input_path.glob("*.pdf"))
    ]


def run_conversion(repo_root: Path, target: ConversionTarget, args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(repo_root / "main.py"),
        "--input",
        str(target.pdf_path),
        "--output",
        str(target.output_dir),
        "--config",
        str(Path(args.config).expanduser()),
        "--extraction-mode",
        str(args.mode),
    ]
    if args.model:
        command.extend(["--model", str(args.model)])
    if args.dry_run:
        command.append("--dry-run")
    if args.force:
        command.append("--force")
    if args.force_vision:
        command.append("--force-vision")
    return subprocess.run(command, cwd=repo_root, stderr=subprocess.STDOUT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
