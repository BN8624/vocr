from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.page_renderer import PageImage


@dataclass(frozen=True)
class ChunkImage:
    chunk_id: str
    page_number: int
    chunk_index: int
    image_path: Path
    width: int
    height: int
    source_y_start: int
    source_y_end: int
    header_y_start: int
    header_y_end: int
    reused: bool


def build_chunks(
    pages: list[PageImage],
    chunks_dir: Path,
    config: dict[str, Any],
    force: bool = False,
) -> list[ChunkImage]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to build page chunks. Run: pip install -r requirements.txt"
        ) from exc

    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[ChunkImage] = []

    for page in pages:
        page_config = _page_config(config, page.page_number)
        with Image.open(page.image_path) as image:
            image = image.convert("RGB")
            width, height = image.size

            header_y_start = 0
            header_y_end = _clamp(int(height * float(page_config["header_ratio"])), 1, height)
            body_y_start = _clamp(int(height * float(page_config["body_start_ratio"])), 0, height - 1)
            body_y_end = _clamp(int(height * float(page_config["body_end_ratio"])), body_y_start + 1, height)
            chunk_height = _clamp(
                int(height * float(page_config["chunk_height_ratio"])),
                1,
                body_y_end - body_y_start,
            )
            overlap = _clamp(int(chunk_height * float(page_config["overlap_ratio"])), 0, chunk_height - 1)
            step = max(1, chunk_height - overlap)
            attach_header = bool(page_config.get("attach_header", True))

            header = image.crop((0, header_y_start, width, header_y_end))
            y_start = body_y_start
            chunk_index = 1

            while y_start < body_y_end:
                y_end = min(y_start + chunk_height, body_y_end)
                chunk_id = f"{page.page_id}_chunk_{chunk_index:02d}"
                output_path = chunks_dir / f"{chunk_id}.png"
                reused = output_path.exists() and not force

                if reused:
                    with Image.open(output_path) as existing:
                        chunk_width, chunk_image_height = existing.size
                else:
                    body = image.crop((0, y_start, width, y_end))
                    if attach_header:
                        chunk_image = Image.new("RGB", (width, header.height + body.height), "white")
                        chunk_image.paste(header, (0, 0))
                        chunk_image.paste(body, (0, header.height))
                    else:
                        chunk_image = body
                    chunk_image.save(output_path)
                    chunk_width, chunk_image_height = chunk_image.size

                chunks.append(
                    ChunkImage(
                        chunk_id=chunk_id,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        image_path=output_path,
                        width=chunk_width,
                        height=chunk_image_height,
                        source_y_start=y_start,
                        source_y_end=y_end,
                        header_y_start=header_y_start,
                        header_y_end=header_y_end if attach_header else 0,
                        reused=reused,
                    )
                )

                if y_end >= body_y_end:
                    break
                y_start += step
                chunk_index += 1

            if bool(page_config.get("bottom_guard_enabled", False)):
                guard_start = _clamp(int(height * float(page_config.get("bottom_guard_start_ratio", 0.90))), body_y_start, body_y_end - 1)
                guard_end = _clamp(int(height * float(page_config.get("bottom_guard_end_ratio", page_config["body_end_ratio"]))), guard_start + 1, body_y_end)
                chunk_id = f"{page.page_id}_chunk_90"
                output_path = chunks_dir / f"{chunk_id}.png"
                reused = output_path.exists() and not force

                if reused:
                    with Image.open(output_path) as existing:
                        chunk_width, chunk_image_height = existing.size
                else:
                    body = image.crop((0, guard_start, width, guard_end))
                    if attach_header:
                        chunk_image = Image.new("RGB", (width, header.height + body.height), "white")
                        chunk_image.paste(header, (0, 0))
                        chunk_image.paste(body, (0, header.height))
                    else:
                        chunk_image = body
                    chunk_image.save(output_path)
                    chunk_width, chunk_image_height = chunk_image.size

                chunks.append(
                    ChunkImage(
                        chunk_id=chunk_id,
                        page_number=page.page_number,
                        chunk_index=90,
                        image_path=output_path,
                        width=chunk_width,
                        height=chunk_image_height,
                        source_y_start=guard_start,
                        source_y_end=guard_end,
                        header_y_start=header_y_start,
                        header_y_end=header_y_end if attach_header else 0,
                        reused=reused,
                    )
                )

    manifest_path = chunks_dir / "chunks_manifest.json"
    manifest_path.write_text(
        json.dumps([_chunk_to_json(chunk) for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chunks


def build_total_chunks(
    pages: list[PageImage],
    chunks_dir: Path,
    config: dict[str, Any],
    force: bool = False,
) -> list[ChunkImage]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to build total review chunks. Run: pip install -r requirements.txt"
        ) from exc

    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[ChunkImage] = []

    for page in pages:
        page_config = _page_config(config, page.page_number)
        header_ratio = float(page_config.get("header_ratio", 0.12))
        summary_start_ratio = float(page_config.get("summary_start_ratio", 0.62))
        summary_end_ratio = float(page_config.get("summary_end_ratio", 0.98))
        attach_header = bool(page_config.get("attach_header", True))

        with Image.open(page.image_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            header_y_start = 0
            header_y_end = _clamp(int(height * header_ratio), 1, height)
            summary_y_start = _clamp(int(height * summary_start_ratio), 0, height - 1)
            summary_y_end = _clamp(int(height * summary_end_ratio), summary_y_start + 1, height)
            chunk_id = f"{page.page_id}_totals_01"
            output_path = chunks_dir / f"{chunk_id}.png"
            reused = output_path.exists() and not force

            if reused:
                with Image.open(output_path) as existing:
                    chunk_width, chunk_height = existing.size
            else:
                summary = image.crop((0, summary_y_start, width, summary_y_end))
                if attach_header:
                    header = image.crop((0, header_y_start, width, header_y_end))
                    chunk_image = Image.new("RGB", (width, header.height + summary.height), "white")
                    chunk_image.paste(header, (0, 0))
                    chunk_image.paste(summary, (0, header.height))
                else:
                    chunk_image = summary
                chunk_image.save(output_path)
                chunk_width, chunk_height = chunk_image.size

            chunks.append(
                ChunkImage(
                    chunk_id=chunk_id,
                    page_number=page.page_number,
                    chunk_index=900,
                    image_path=output_path,
                    width=chunk_width,
                    height=chunk_height,
                    source_y_start=summary_y_start,
                    source_y_end=summary_y_end,
                    header_y_start=header_y_start,
                    header_y_end=header_y_end if attach_header else 0,
                    reused=reused,
                )
            )

    manifest_path = chunks_dir / "total_chunks_manifest.json"
    manifest_path.write_text(
        json.dumps([_chunk_to_json(chunk) for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chunks


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _page_config(config: dict[str, Any], page_number: int) -> dict[str, Any]:
    merged = {key: value for key, value in config.items() if key != "__page_overrides"}
    overrides = config.get("__page_overrides", {})
    if not isinstance(overrides, dict):
        return merged
    page_override = overrides.get(str(page_number)) or overrides.get(page_number)
    if isinstance(page_override, dict):
        merged.update(page_override)
    return merged


def _chunk_to_json(chunk: ChunkImage) -> dict[str, object]:
    data = asdict(chunk)
    data["image_path"] = str(chunk.image_path)
    return data
