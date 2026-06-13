from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CacheReport:
    output_dir: Path
    expected_chunk_count: int
    cached_count: int
    missing_chunk_ids: list[str]
    error_chunk_ids: list[str]

    @property
    def ready(self) -> bool:
        return (
            self.expected_chunk_count > 0
            and self.cached_count == self.expected_chunk_count
            and not self.missing_chunk_ids
            and not self.error_chunk_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "output_dir": str(self.output_dir),
            "expected_chunk_count": self.expected_chunk_count,
            "cached_count": self.cached_count,
            "missing_count": len(self.missing_chunk_ids),
            "error_count": len(self.error_chunk_ids),
            "ready_for_cache_only_tests": self.ready,
            "missing_chunk_ids": self.missing_chunk_ids,
            "error_chunk_ids": self.error_chunk_ids,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether an output folder has complete Vision JSON cache files."
    )
    parser.add_argument("--output", required=True, help="Pipeline output folder to inspect.")
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Also write merged/vision_cache_report.json.",
    )
    args = parser.parse_args()

    report = check_cache(Path(args.output).expanduser().resolve())
    if args.write_report:
        report_path = report.output_dir / "merged" / "vision_cache_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {report_path}")

    print_summary(report)
    return 0 if report.ready else 1


def check_cache(output_dir: Path) -> CacheReport:
    chunk_ids = sorted(set(_load_chunk_ids(output_dir / "chunks" / "chunks_manifest.json")))
    chunk_ids.extend(
        chunk_id
        for chunk_id in _load_chunk_ids(output_dir / "total_chunks" / "total_chunks_manifest.json")
        if chunk_id not in chunk_ids
    )

    cache_dir = output_dir / "cache"
    missing: list[str] = []
    errors: list[str] = []
    cached_count = 0
    for chunk_id in chunk_ids:
        cache_path = cache_dir / f"{chunk_id}.vision.json"
        error_path = cache_path.with_suffix(".error.json")
        if cache_path.exists():
            cached_count += 1
        elif error_path.exists():
            errors.append(chunk_id)
        else:
            missing.append(chunk_id)

    return CacheReport(
        output_dir=output_dir,
        expected_chunk_count=len(chunk_ids),
        cached_count=cached_count,
        missing_chunk_ids=missing,
        error_chunk_ids=errors,
    )


def _load_chunk_ids(manifest_path: Path) -> list[str]:
    payload = _read_json(manifest_path)
    if not isinstance(payload, list):
        return []

    chunk_ids: list[str] = []
    for item in payload:
        if isinstance(item, str):
            chunk_id = item
        elif isinstance(item, dict):
            chunk_id = str(item.get("chunk_id") or item.get("id") or item.get("chunkId") or "")
        else:
            chunk_id = ""
        if chunk_id:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def print_summary(report: CacheReport) -> None:
    print(f"Output: {report.output_dir}")
    print(f"Expected chunks: {report.expected_chunk_count}")
    print(f"Cached Vision JSON: {report.cached_count}")
    print(f"Error cache files: {len(report.error_chunk_ids)}")
    print(f"Missing cache files: {len(report.missing_chunk_ids)}")
    print(f"Ready for cache-only tests: {'yes' if report.ready else 'no'}")

    if report.error_chunk_ids:
        print("Error chunks:")
        for chunk_id in report.error_chunk_ids:
            print(f"  - {chunk_id}")
    if report.missing_chunk_ids:
        print("Missing chunks:")
        for chunk_id in report.missing_chunk_ids:
            print(f"  - {chunk_id}")


if __name__ == "__main__":
    raise SystemExit(main())
