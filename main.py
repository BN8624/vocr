from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from src.chunk_builder import build_chunks
from src.page_renderer import render_pdf_pages
from src.review_builder import build_review_html
from src.vision_extractor import extract_chunks_with_vision, load_cached_vision_results


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
    "vision": {
        "provider": "gemini",
        "model": "gemini-3.5-flash",
        "api_key_env": "GEMINI_API_KEY",
        "prompt_path": "prompts/vision_extract_table.md",
        "request_delay_seconds": 5,
        "timeout_seconds": 120,
        "cache_enabled": True,
        "max_retries": 1,
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
    phase: str,
    llm_calls: int,
    vision_ok: int,
    vision_errors: int,
) -> Path:
    summary_path = output_dir / config["output"]["summary_filename"]
    summary = {
        "input_pdf": str(input_pdf),
        "page_count": page_count,
        "chunk_count": chunk_count,
        "review_html": str(review_path),
        "phase": phase,
        "llm_calls": llm_calls,
        "vision_ok": vision_ok,
        "vision_errors": vision_errors,
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
    parser.add_argument(
        "--force-vision",
        action="store_true",
        help="Call the Vision LLM again even when cached JSON exists.",
    )
    parser.add_argument(
        "--limit-chunks",
        type=int,
        default=None,
        help="Process only the first N chunks with Vision LLM. Useful for API smoke tests.",
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

        vision_results = []
        llm_calls = 0
        if args.dry_run:
            logging.info("Dry-run mode: skipping Vision LLM calls.")
            vision_results = load_cached_vision_results(chunks, output_dirs["cache"])
            phase = "phase_1_dry_run"
        else:
            logging.info("Extracting rows with Gemini Vision...")
            prompt_path = Path(str(config["vision"]["prompt_path"]))
            if not prompt_path.is_absolute():
                prompt_path = config_path.parent / prompt_path
            vision_results = extract_chunks_with_vision(
                chunks=chunks,
                cache_dir=output_dirs["cache"],
                prompt_path=prompt_path,
                config=config["vision"],
                force=bool(args.force_vision),
                limit=args.limit_chunks,
            )
            llm_calls = sum(1 for result in vision_results if not result.reused)
            phase = "phase_2_3_vision_review"

        logging.info("Building review HTML...")
        review_path = build_review_html(
            output_dir=output_dirs["root"],
            pages=pages,
            chunks=chunks,
            config=config["review"],
            input_pdf=input_pdf,
            vision_results=vision_results,
        )

        summary_path = write_summary(
            output_dir=output_dirs["root"],
            config=config,
            input_pdf=input_pdf,
            page_count=len(pages),
            chunk_count=len(chunks),
            review_path=review_path,
            phase=phase,
            llm_calls=llm_calls,
            vision_ok=sum(1 for result in vision_results if result.data is not None),
            vision_errors=sum(1 for result in vision_results if result.status == "error"),
        )

    except Exception as exc:
        logging.error("Could not complete pipeline: %s", exc)
        return 1

    logging.info("Done. Review file: %s", review_path)
    logging.info("Summary file: %s", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
