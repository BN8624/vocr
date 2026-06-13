from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a JSON manifest from card statement sample PDFs.")
    parser.add_argument("--samples", default="견본", help="Folder containing sample PDFs.")
    parser.add_argument("--output", default="", help="Output manifest path. Default: <samples>/sample_manifest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples_dir = Path(args.samples).expanduser().resolve()
    output_path = Path(args.output).expanduser() if args.output else samples_dir / "sample_manifest.json"
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    manifest = build_manifest(samples_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(manifest)} samples: {output_path}")
    return 0


def build_manifest(samples_dir: Path) -> list[dict[str, Any]]:
    if not samples_dir.exists():
        raise FileNotFoundError(f"Sample folder not found: {samples_dir}")
    rows = []
    for pdf_path in sorted(samples_dir.glob("*.pdf"), key=lambda path: path.name):
        parsed = parse_sample_name(pdf_path)
        rows.append(
            {
                "sample_id": parsed["sample_id"],
                "issuer": parsed["issuer"],
                "path": _portable_path(pdf_path),
                "expected_pages": parsed["expected_pages"],
                "sample_type": sample_type(parsed["expected_pages"]),
            }
        )
    if not rows:
        raise FileNotFoundError(f"No PDF samples found: {samples_dir}")
    return rows


def parse_sample_name(pdf_path: Path) -> dict[str, Any]:
    stem = pdf_path.stem
    match = re.match(r"^(?P<issuer>.+)_(?P<pages>\d+)$", stem)
    if not match:
        return {
            "sample_id": safe_id(stem),
            "issuer": stem,
            "expected_pages": None,
        }
    issuer = match.group("issuer")
    expected_pages = int(match.group("pages"))
    return {
        "sample_id": safe_id(stem),
        "issuer": issuer,
        "expected_pages": expected_pages,
    }


def sample_type(expected_pages: int | None) -> str:
    if expected_pages == 1:
        return "single_page"
    if expected_pages == 2:
        return "two_pages"
    if expected_pages == 3:
        return "three_pages"
    if expected_pages is None:
        return "unknown_pages"
    return "multi_page"


def safe_id(value: str) -> str:
    cleaned = []
    for char in value.strip():
        if char.isalnum():
            cleaned.append(char.lower())
        elif char in {"-", "_", " "}:
            cleaned.append("_")
    sample_id = re.sub(r"_+", "_", "".join(cleaned)).strip("_")
    return sample_id or "sample"


def _portable_path(path: Path) -> str:
    return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
