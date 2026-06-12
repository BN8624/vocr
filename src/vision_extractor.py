from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.chunk_builder import ChunkImage


@dataclass(frozen=True)
class VisionResult:
    chunk_id: str
    page_number: int
    cache_path: Path
    status: str
    data: dict[str, Any] | None
    error_path: Path | None = None
    raw_text_path: Path | None = None
    reused: bool = False


VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "page": {"type": "integer"},
        "chunk_id": {"type": "string"},
        "header": {"type": "array", "items": {"type": "string"}},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "local_row_index": {"type": "integer"},
                    "cells": {"type": "array", "items": {"type": "string"}},
                    "line_text": {"type": "string"},
                    "needs_review": {"type": "boolean"},
                    "review_reason": {"type": "string"},
                    "confidence_note": {"type": "string"},
                },
                "required": [
                    "local_row_index",
                    "cells",
                    "line_text",
                    "needs_review",
                    "review_reason",
                    "confidence_note",
                ],
            },
        },
        "totals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value_text": {"type": "string"},
                    "amount": {"type": "integer"},
                    "needs_review": {"type": "boolean"},
                    "review_reason": {"type": "string"},
                },
                "required": ["label", "value_text", "amount", "needs_review", "review_reason"],
            },
        },
        "needs_review": {"type": "boolean"},
        "review_reason": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": [
        "schema_version",
        "page",
        "chunk_id",
        "header",
        "rows",
        "totals",
        "needs_review",
        "review_reason",
        "notes",
    ],
}


def extract_chunks_with_vision(
    chunks: list[ChunkImage],
    cache_dir: Path,
    prompt_path: Path,
    config: dict[str, Any],
    force: bool = False,
    limit: int | None = None,
) -> list[VisionResult]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    api_key = _load_api_key(config)
    prompt = _load_prompt(prompt_path)

    selected_chunks = chunks[:limit] if limit is not None else chunks
    results: list[VisionResult] = []
    for index, chunk in enumerate(selected_chunks, start=1):
        cache_path = cache_dir / f"{chunk.chunk_id}.vision.json"
        if cache_path.exists() and not force:
            results.append(
                VisionResult(
                    chunk_id=chunk.chunk_id,
                    page_number=chunk.page_number,
                    cache_path=cache_path,
                    status="cached",
                    data=_read_json(cache_path),
                    reused=True,
                )
            )
            continue

        result = _extract_one_chunk(
            chunk=chunk,
            cache_path=cache_path,
            api_key=api_key,
            prompt=prompt,
            config=config,
        )
        results.append(result)

        delay = float(config.get("request_delay_seconds", 0))
        if delay > 0 and index < len(selected_chunks):
            time.sleep(delay)

    return results


def load_cached_vision_results(chunks: list[ChunkImage], cache_dir: Path) -> list[VisionResult]:
    results: list[VisionResult] = []
    for chunk in chunks:
        cache_path = cache_dir / f"{chunk.chunk_id}.vision.json"
        error_path = cache_dir / f"{chunk.chunk_id}.error.json"
        raw_text_path = cache_dir / f"{chunk.chunk_id}.invalid.txt"

        if cache_path.exists():
            results.append(
                VisionResult(
                    chunk_id=chunk.chunk_id,
                    page_number=chunk.page_number,
                    cache_path=cache_path,
                    status="cached",
                    data=_read_json(cache_path),
                    reused=True,
                )
            )
        elif error_path.exists():
            results.append(
                VisionResult(
                    chunk_id=chunk.chunk_id,
                    page_number=chunk.page_number,
                    cache_path=cache_path,
                    status="error",
                    data=None,
                    error_path=error_path,
                    raw_text_path=raw_text_path if raw_text_path.exists() else None,
                    reused=True,
                )
            )
    return results


def _extract_one_chunk(
    chunk: ChunkImage,
    cache_path: Path,
    api_key: str,
    prompt: str,
    config: dict[str, Any],
) -> VisionResult:
    error_path = cache_path.with_suffix(".error.json")
    raw_text_path = cache_path.with_suffix(".invalid.txt")
    max_retries = max(1, int(config.get("max_retries", 1)))

    try:
        last_error: Exception | None = None
        response: dict[str, Any] | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = _call_gemini(
                    api_key=api_key,
                    model=str(config["model"]),
                    image_path=chunk.image_path,
                    prompt=_chunk_prompt(prompt, chunk),
                    timeout_seconds=int(config.get("timeout_seconds", 120)),
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    time.sleep(float(config.get("request_delay_seconds", 0)))
        if response is None:
            raise RuntimeError(f"Gemini extraction failed after {max_retries} attempt(s): {last_error}")

        text = _extract_text(response)
        try:
            data = _parse_json_text(text)
        except Exception:
            raw_text_path.write_text(text, encoding="utf-8")
            raise
        data = _with_required_defaults(data, chunk)
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _remove_if_exists(error_path)
        _remove_if_exists(raw_text_path)
        return VisionResult(
            chunk_id=chunk.chunk_id,
            page_number=chunk.page_number,
            cache_path=cache_path,
            status="ok",
            data=data,
        )
    except Exception as exc:
        error = {
            "chunk_id": chunk.chunk_id,
            "page": chunk.page_number,
            "status": "error",
            "message": str(exc),
        }
        error_path.write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
        return VisionResult(
            chunk_id=chunk.chunk_id,
            page_number=chunk.page_number,
            cache_path=cache_path,
            status="error",
            data=None,
            error_path=error_path,
            raw_text_path=raw_text_path if raw_text_path.exists() else None,
        )


def _call_gemini(
    api_key: str,
    model: str,
    image_path: Path,
    prompt: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    image_bytes = image_path.read_bytes()
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "responseFormat": {
                "text": {
                    "mimeType": "application/json",
                    "schema": VISION_SCHEMA,
                }
            }
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc


def _extract_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini response has no candidates.")
    parts = candidates[0].get("content", {}).get("parts") or []
    texts = [str(part.get("text", "")) for part in parts if part.get("text")]
    if not texts:
        raise ValueError("Gemini response has no text part.")
    return "\n".join(texts).strip()


def _parse_json_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").removesuffix("```").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Gemini response JSON must be an object.")
    return data


def _with_required_defaults(data: dict[str, Any], chunk: ChunkImage) -> dict[str, Any]:
    data.setdefault("schema_version", "1.0")
    data["page"] = int(data.get("page") or chunk.page_number)
    data["chunk_id"] = str(data.get("chunk_id") or chunk.chunk_id)
    data.setdefault("header", [])
    data.setdefault("rows", [])
    data.setdefault("totals", [])
    data.setdefault("needs_review", False)
    data.setdefault("review_reason", "")
    data.setdefault("notes", "")

    for index, row in enumerate(data["rows"], start=1):
        if not isinstance(row, dict):
            continue
        row.setdefault("local_row_index", index)
        row.setdefault("cells", [])
        row.setdefault("line_text", "")
        row.setdefault("needs_review", False)
        row.setdefault("review_reason", "")
        row.setdefault("confidence_note", "")

    return data


def _chunk_prompt(prompt: str, chunk: ChunkImage) -> str:
    return (
        f"{prompt}\n\n"
        f"Chunk metadata:\n"
        f"- page: {chunk.page_number}\n"
        f"- chunk_id: {chunk.chunk_id}\n"
        f"- local row indexes must start at 1 within this chunk.\n"
    )


def _load_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Vision prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _load_api_key(config: dict[str, Any]) -> str:
    env_name = str(config.get("api_key_env", "GEMINI_API_KEY"))
    api_key = os.environ.get(env_name) or _read_dotenv_value(Path(".env"), env_name)
    if not api_key:
        raise RuntimeError(
            f"Missing Gemini API key. Set {env_name} in the environment or in .env."
        )
    return api_key


def _read_dotenv_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()
