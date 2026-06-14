from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from src.chunk_builder import build_chunks, build_total_chunks
from src.page_extractor import extract_pages_with_vision, page_pseudo_chunks
from src.automation import write_automation_summary
from src.excel_exporter import export_excel, load_excel_export
from src.normalizer import build_transactions, load_normalization_output
from src.page_renderer import render_pdf_pages
from src.profile_store import build_mapping_suggestions, load_mapping_suggestions
from src.reconciliation import write_section_reconciliation
from src.review_builder import build_review_html
from src.row_merger import build_row_outputs, load_merge_output
from src.validator import build_validation, load_validation_output
from src.vision_extractor import extract_chunks_with_vision, load_cached_vision_results


DEFAULT_CONFIG: dict[str, Any] = {
    "extraction": {"mode": "chunk", "page_prompt_path": "prompts/page_extract_jsonl.md"},
    "render": {"dpi": 300, "image_format": "png"},
    "chunking": {
        "header_ratio": 0.12,
        "body_start_ratio": 0.12,
        "body_end_ratio": 0.95,
        "chunk_height_ratio": 0.35,
        "overlap_ratio": 0.25,
        "attach_header": True,
        "bottom_guard_enabled": True,
        "bottom_guard_start_ratio": 0.90,
        "bottom_guard_end_ratio": 0.98,
    },
    "total_extraction": {
        "enabled": True,
        "header_ratio": 0.12,
        "summary_start_ratio": 0.62,
        "summary_end_ratio": 0.98,
        "attach_header": True,
        "prompt_path": "prompts/vision_extract_totals.md",
    },
    "review": {
        "html_title": "Card Statement Review",
        "show_chunk_images": True,
        "show_raw_json_paths": True,
    },
    "vision": {
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "api_key_env": "GEMINI_API_KEY",
        "prompt_path": "prompts/vision_extract_table.md",
        "request_delay_seconds": 5,
        "timeout_seconds": 120,
        "cache_enabled": True,
        "max_retries": 4,
        "concurrency": 2,
        "rpm_limit": 15,
        "max_output_tokens": 65535,
        "adaptive_preprocess": True,
    },
    "output": {
        "pages_dir": "pages",
        "chunks_dir": "chunks",
        "total_chunks_dir": "total_chunks",
        "cache_dir": "cache",
        "merged_dir": "merged",
        "profiles_dir": "profiles",
        "summary_filename": "summary.json",
    },
    "export": {"excel_filename": "result.xlsx"},
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
        "total_chunks": output_dir / output_cfg.get("total_chunks_dir", "total_chunks"),
        "cache": output_dir / output_cfg["cache_dir"],
        "merged": output_dir / output_cfg["merged_dir"],
        "profiles": Path(output_cfg.get("profiles_dir", "profiles")),
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def load_review_state(merged_dir: Path) -> dict[str, Any]:
    state_path = merged_dir / "review_state.json"
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.info("Review state is not valid JSON, ignoring: %s", state_path)
        return {}
    return payload if isinstance(payload, dict) else {}


def load_page_crop_profile(merged_dir: Path) -> dict[str, Any]:
    profile_path = merged_dir / "page_crop_profile.json"
    if not profile_path.exists():
        return {}
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.info("Page crop profile is not valid JSON, ignoring: %s", profile_path)
        return {}
    return payload if isinstance(payload, dict) else {}


def apply_page_crop_profile(section_config: dict[str, Any], profile: dict[str, Any], section: str) -> dict[str, Any]:
    pages = profile.get("pages", {}) if isinstance(profile.get("pages"), dict) else {}
    overrides: dict[str, dict[str, Any]] = {}
    for page_number, page_data in pages.items():
        if not isinstance(page_data, dict):
            continue
        section_data = page_data.get(section, {})
        if isinstance(section_data, dict) and section_data:
            overrides[str(page_number)] = section_data
    if not overrides:
        return section_config
    merged = dict(section_config)
    merged["__page_overrides"] = overrides
    return merged


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
    raw_row_count: int,
    duplicate_group_count: int,
    mapping_group_count: int,
    transaction_count: int,
    normalization_review_count: int,
    normalized_amount_total: int,
    validation_issue_row_count: int,
    checksum_status: str,
    excel_path: Path | None,
    automation_summary_path: Path | None = None,
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
        "raw_row_count": raw_row_count,
        "duplicate_group_count": duplicate_group_count,
        "mapping_group_count": mapping_group_count,
        "transaction_count": transaction_count,
        "normalization_review_count": normalization_review_count,
        "normalized_amount_total": normalized_amount_total,
        "validation_issue_row_count": validation_issue_row_count,
        "checksum_status": checksum_status,
        "excel_path": str(excel_path) if excel_path else "",
        "automation_summary": str(automation_summary_path) if automation_summary_path else "",
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
    parser.add_argument(
        "--skip-total-pass",
        action="store_true",
        help="Skip the targeted summary/total extraction pass.",
    )
    parser.add_argument(
        "--extraction-mode",
        choices=["chunk", "page"],
        default=None,
        help="Override extraction.mode: chunk(겹침 청크) 또는 page(페이지 단위 헤더키).",
    )
    parser.add_argument(
        "--mapping-profile",
        action="append",
        default=[],
        help="Apply a downloaded mapping-profile.json file. Can be passed multiple times.",
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
        if args.extraction_mode:
            config.setdefault("extraction", {})["mode"] = args.extraction_mode
        output_dirs = ensure_output_dirs(output_dir, config)
        page_crop_profile = load_page_crop_profile(output_dirs["merged"])

        logging.info("Rendering PDF pages...")
        pages = render_pdf_pages(
            pdf_path=input_pdf,
            pages_dir=output_dirs["pages"],
            dpi=int(config["render"]["dpi"]),
            image_format=str(config["render"]["image_format"]),
            force=bool(args.force),
        )

        extraction_mode = str(config.get("extraction", {}).get("mode", "chunk")).lower()

        if extraction_mode == "page":
            logging.info("Page-mode extraction: one Vision call per full page.")
            review_chunks = page_pseudo_chunks(pages)
            chunks = review_chunks
            total_chunks = []

            vision_results = []
            llm_calls = 0
            if args.dry_run:
                logging.info("Dry-run mode: skipping Vision LLM calls.")
                vision_results = load_cached_vision_results(review_chunks, output_dirs["cache"])
                phase = "phase_1_dry_run"
            else:
                logging.info("Extracting rows with Gemini Vision (page mode)...")
                page_prompt_path = Path(str(config.get("extraction", {}).get("page_prompt_path", "prompts/page_extract_jsonl.md")))
                if not page_prompt_path.is_absolute():
                    page_prompt_path = config_path.parent / page_prompt_path
                vision_results = extract_pages_with_vision(
                    pages=pages,
                    cache_dir=output_dirs["cache"],
                    prompt_path=page_prompt_path,
                    config=config["vision"],
                    force=bool(args.force_vision),
                )
                llm_calls = sum(1 for result in vision_results if not result.reused)
                phase = "phase_2_3_vision_review"
        else:
            logging.info("Building overlapping review chunks...")
            chunks = build_chunks(
                pages=pages,
                chunks_dir=output_dirs["chunks"],
                config=apply_page_crop_profile(config["chunking"], page_crop_profile, "chunking"),
                force=bool(args.force),
            )
            total_chunks = []
            if bool(config.get("total_extraction", {}).get("enabled", True)) and not args.skip_total_pass:
                logging.info("Building targeted total review chunks...")
                total_chunks = build_total_chunks(
                    pages=pages,
                    chunks_dir=output_dirs["total_chunks"],
                    config=apply_page_crop_profile(
                        config.get("total_extraction", {}),
                        page_crop_profile,
                        "total_extraction",
                    ),
                    force=bool(args.force),
                )
            review_chunks = chunks + total_chunks

            vision_results = []
            llm_calls = 0
            if args.dry_run:
                logging.info("Dry-run mode: skipping Vision LLM calls.")
                vision_results = load_cached_vision_results(chunks, output_dirs["cache"])
                vision_results.extend(load_cached_vision_results(total_chunks, output_dirs["cache"]))
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
                if total_chunks:
                    logging.info("Extracting summary totals with Gemini Vision...")
                    total_prompt_path = Path(str(config.get("total_extraction", {}).get("prompt_path", "prompts/vision_extract_totals.md")))
                    if not total_prompt_path.is_absolute():
                        total_prompt_path = config_path.parent / total_prompt_path
                    vision_results.extend(
                        extract_chunks_with_vision(
                            chunks=total_chunks,
                            cache_dir=output_dirs["cache"],
                            prompt_path=total_prompt_path,
                            config=config["vision"],
                            force=bool(args.force_vision),
                        )
                    )
                llm_calls = sum(1 for result in vision_results if not result.reused)
                phase = "phase_2_3_vision_review"

        merge_output = None
        if vision_results:
            logging.info("Collecting raw rows and duplicate candidates...")
            merge_output = build_row_outputs(
                vision_results=vision_results,
                chunks=review_chunks,
                input_pdf=input_pdf,
                output_dir=output_dirs["root"],
                merged_dir=output_dirs["merged"],
            )
            if args.dry_run:
                phase = "phase_4_cached_review"
        else:
            merge_output = load_merge_output(output_dirs["merged"])

        mapping_output = None
        if merge_output:
            logging.info("Building column mapping suggestions...")
            profile_paths = [Path(path).expanduser().resolve() for path in args.mapping_profile]
            mapping_output = build_mapping_suggestions(
                merge_output=merge_output,
                output_dir=output_dirs["root"],
                profiles_dir=output_dirs["profiles"],
                profile_paths=profile_paths,
            )
            phase = "phase_5_mapping_review"
        else:
            mapping_output = load_mapping_suggestions(
                output_dir=output_dirs["root"],
                profiles_dir=output_dirs["profiles"],
            )

        normalization_output = None
        if merge_output and mapping_output:
            logging.info("Normalizing mapped rows into transactions...")
            normalization_output = build_transactions(
                merge_output=merge_output,
                mapping_output=mapping_output,
                merged_dir=output_dirs["merged"],
            )
            phase = "phase_6_normalized_review"
        else:
            normalization_output = load_normalization_output(output_dirs["merged"])

        validation_output = None
        if normalization_output:
            logging.info("Validating normalized transactions...")
            review_state = load_review_state(output_dirs["merged"])
            validation_output = build_validation(
                normalization_output=normalization_output,
                vision_results=vision_results,
                merged_dir=output_dirs["merged"],
                expected_chunk_count=len(review_chunks),
                review_state=review_state,
            )
            phase = "phase_7_validated_review"
        else:
            validation_output = load_validation_output(output_dirs["merged"])

        automation_summary_path = write_automation_summary(
            validation_output=validation_output,
            normalization_output=normalization_output,
            merged_dir=output_dirs["merged"],
        )
        section_reconciliation_path = write_section_reconciliation(
            validation_output=validation_output,
            merged_dir=output_dirs["merged"],
        )

        excel_output = None
        if validation_output:
            logging.info("Exporting reviewable Excel workbook...")
            excel_output = export_excel(
                validation_output=validation_output,
                output_dir=output_dirs["root"],
                filename=str(config.get("export", {}).get("excel_filename", "result.xlsx")),
                source_rows_path=merge_output.rows_merged_path if merge_output else None,
            )
            phase = "phase_8_excel_export"
        else:
            excel_output = load_excel_export(
                output_dir=output_dirs["root"],
                filename=str(config.get("export", {}).get("excel_filename", "result.xlsx")),
            )

        logging.info("Building review HTML...")
        review_path = build_review_html(
            output_dir=output_dirs["root"],
            pages=pages,
            chunks=review_chunks,
            config=config["review"],
            input_pdf=input_pdf,
            vision_results=vision_results,
            merge_output=merge_output,
            mapping_output=mapping_output,
            normalization_output=normalization_output,
            validation_output=validation_output,
            excel_output=excel_output,
        )

        summary_path = write_summary(
            output_dir=output_dirs["root"],
            config=config,
            input_pdf=input_pdf,
            page_count=len(pages),
            chunk_count=len(review_chunks),
            review_path=review_path,
            phase=phase,
            llm_calls=llm_calls,
            vision_ok=sum(1 for result in vision_results if result.data is not None),
            vision_errors=sum(1 for result in vision_results if result.status == "error"),
            raw_row_count=merge_output.raw_row_count if merge_output else 0,
            duplicate_group_count=merge_output.duplicate_group_count if merge_output else 0,
            mapping_group_count=len(mapping_output.table_groups) if mapping_output else 0,
            transaction_count=normalization_output.transaction_count if normalization_output else 0,
            normalization_review_count=normalization_output.review_count if normalization_output else 0,
            normalized_amount_total=normalization_output.amount_total if normalization_output else 0,
            validation_issue_row_count=validation_output.issue_row_count if validation_output else 0,
            checksum_status=validation_output.checksum_status if validation_output else "not_run",
            excel_path=excel_output.workbook_path if excel_output else None,
            automation_summary_path=automation_summary_path,
        )

    except Exception as exc:
        logging.error("Could not complete pipeline: %s", exc)
        return 1

    logging.info("Done. Review file: %s", review_path)
    logging.info("Summary file: %s", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
