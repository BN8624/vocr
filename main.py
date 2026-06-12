from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from src.chunk_builder import build_chunks
from src.page_renderer import render_pdf_pages
from src.review_builder import build_review_html


DEFAULT_CONFIG: dict[str, Any] = {
    "render": {"dpi": 300, "image_format": "png"},
    "chunking": {
        "header_ratio": 0.12,
        "body_start_ratio": 0.12,
        "body_end_ratio": 0.95,
        "chunk_height_ratio": 0.35,
        "overlap_ratio": 0.25,
        "attach_header": True,
    },
    "review": {
        "html_title": "Card Statement Review",
        "show_chunk_images": True,
        "show_raw_json_paths": True,
    },
    "output": {
        "pages_dir": "pages",
        "chunks_dir": "chunks",
        "cache_dir": "cache",
        "merged_dir": "merged",
        "summary_filename": "summary.json",
    },
}


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        logging.info("Config file not found, using built-in defaults: %s", path)
        return DEFAULT_CONFIG

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to read config.yaml. Run: pip install -r requirements.txt"
        ) from exc

    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config must be a YAML mapping: {path}")
    return deep_merge(DEFAULT_CONFIG, loaded)


def ensure_output_dirs(output_dir: Path, config: dict[str, Any]) -> dict[str, Path]:
    output_cfg = config["output"]
    dirs = {
        "root": output_dir,
        "pages": output_dir / output_cfg["pages_dir"],
        "chunks": output_dir / output_cfg["chunks_dir"],
        "cache": output_dir / output_cfg["cache_dir"],
        "merged": output_dir / output_cfg["merged_dir"],
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def write_summary(
    output_dir: Path,
    config: dict[str, Any],
    input_pdf: Path,
    page_count: int,
    chunk_count: int,
    review_path: Path,
) -> Path:
    summary_path = output_dir / config["output"]["summary_filename"]
    summary = {
        "input_pdf": str(input_pdf),
        "page_count": page_count,
        "chunk_count": chunk_count,
        "review_html": str(review_path),
        "phase": "phase_1_dry_run",
        "llm_calls": 0,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build page images, review chunks, and review.html for card statement PDFs."
    )
    parser.add_argument("--input", required=True, help="Input image-based PDF path.")
    parser.add_argument("--output", default="output", help="Output folder path.")
    parser.add_argument("--config", default="config.yaml", help="YAML config path.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without any external Vision LLM calls.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild rendered pages and chunks even when cached files exist.",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    input_pdf = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()

    if not input_pdf.exists():
        logging.error("Input PDF not found: %s", input_pdf)
        return 2
    if input_pdf.suffix.lower() != ".pdf":
        logging.error("Input must be a PDF file: %s", input_pdf)
        return 2
    if not args.dry_run:
        logging.info("Only Phase 1 is implemented, so this run will not call any LLM API.")

    try:
        config = load_config(config_path)
        output_dirs = ensure_output_dirs(output_dir, config)

        logging.info("Rendering PDF pages...")
        pages = render_pdf_pages(
            pdf_path=input_pdf,
            pages_dir=output_dirs["pages"],
            dpi=int(config["render"]["dpi"]),
            image_format=str(config["render"]["image_format"]),
            force=bool(args.force),
        )

        logging.info("Building overlapping review chunks...")
        chunks = build_chunks(
            pages=pages,
            chunks_dir=output_dirs["chunks"],
            config=config["chunking"],
            force=bool(args.force),
        )

        logging.info("Building review HTML...")
        review_path = build_review_html(
            output_dir=output_dirs["root"],
            pages=pages,
            chunks=chunks,
            config=config["review"],
            input_pdf=input_pdf,
        )

        summary_path = write_summary(
            output_dir=output_dirs["root"],
            config=config,
            input_pdf=input_pdf,
            page_count=len(pages),
            chunk_count=len(chunks),
            review_path=review_path,
        )

    except Exception as exc:
        logging.error("Could not complete Phase 1: %s", exc)
        return 1

    logging.info("Done. Review file: %s", review_path)
    logging.info("Summary file: %s", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
