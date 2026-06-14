# 페이지 1장=1 호출 방식으로 카드 명세서를 헤더명 키 JSON Lines로 추출하는 1단 범용 추출기
"""
sop010.html의 강점을 Python으로 이식한 페이지 단위 추출기.

- 페이지 1장을 통째로 1회 호출(청크·하단가드 없음)해서 겹침 중복과 열밀림을 원천 차단한다.
- 출력은 text/plain + JSON Lines. 헤더명을 동적 키로 받고, 헤더 순서에 맞춘 cells 배열을 재구성해
  기존 row_merger/normalizer/validator(2단)가 그대로 동작하도록 한다.
- 1쪽을 단독 선처리해 헤더를 확정한 뒤, 2쪽~는 동시성 2 + RPM 슬라이딩 큐로 처리하며
  확정 헤더를 knownHeader 힌트로 주입한다.
- 캐시 키는 page_NNN.vision.json으로 기존 청크 캐시(chunk_id)와 분리한다.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from src.chunk_builder import ChunkImage
from src.page_renderer import PageImage
from src.vision_extractor import VisionResult, _load_api_key, _load_prompt


def page_pseudo_chunks(pages: list[PageImage]) -> list[ChunkImage]:
    # 페이지 단위 추출은 페이지 1장을 단일 청크로 본다. row_merger/review가 기대하는 ChunkImage 형태로 감싼다.
    return [
        ChunkImage(
            chunk_id=page.page_id,
            page_number=page.page_number,
            chunk_index=0,
            image_path=page.image_path,
            width=page.width,
            height=page.height,
            source_y_start=0,
            source_y_end=page.height,
            header_y_start=0,
            header_y_end=0,
            reused=page.reused,
        )
        for page in pages
    ]


class _SlidingWindowRateLimiter:
    # 최근 window_seconds 내 호출 수를 limit으로 제한하는 슬라이딩 윈도우 큐.
    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = max(1, int(limit))
        self._window = float(window_seconds)
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= self._window:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._limit:
                    self._timestamps.append(now)
                    return
                wait = self._window - (now - self._timestamps[0]) + 0.02
            if wait > 0:
                time.sleep(wait)


def extract_pages_with_vision(
    pages: list[PageImage],
    cache_dir: Path,
    prompt_path: Path,
    config: dict[str, Any],
    force: bool = False,
) -> list[VisionResult]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    api_key = _load_api_key(config)
    prompt = _load_prompt(prompt_path)

    rpm_limit = int(config.get("rpm_limit", 10))
    rpm_slot = max(1, rpm_limit - 2)
    concurrency = max(1, int(config.get("concurrency", 2)))
    limiter = _SlidingWindowRateLimiter(rpm_slot, 60.0)

    ordered = sorted(pages, key=lambda p: p.page_number)
    results_by_page: dict[int, VisionResult] = {}
    known_header: list[str] | None = None

    # 1쪽 단독 선처리 → 헤더 확정
    if ordered:
        first = ordered[0]
        first_result = _extract_one_page(
            page=first,
            cache_dir=cache_dir,
            api_key=api_key,
            prompt=prompt,
            config=config,
            known_header=None,
            force=force,
            limiter=limiter,
        )
        results_by_page[first.page_number] = first_result
        if first_result.data:
            header = [str(h) for h in first_result.data.get("header", [])]
            if header:
                known_header = header

    # 2쪽~ 동시 처리(헤더 힌트 주입)
    rest = ordered[1:]
    if rest:
        def worker(page: PageImage) -> tuple[int, VisionResult]:
            return page.page_number, _extract_one_page(
                page=page,
                cache_dir=cache_dir,
                api_key=api_key,
                prompt=prompt,
                config=config,
                known_header=known_header,
                force=force,
                limiter=limiter,
            )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for page_number, result in executor.map(worker, rest):
                results_by_page[page_number] = result

    return [results_by_page[page.page_number] for page in ordered]


def _extract_one_page(
    page: PageImage,
    cache_dir: Path,
    api_key: str,
    prompt: str,
    config: dict[str, Any],
    known_header: list[str] | None,
    force: bool,
    limiter: _SlidingWindowRateLimiter,
) -> VisionResult:
    cache_path = cache_dir / f"{page.page_id}.vision.json"
    if cache_path.exists() and not force:
        return VisionResult(
            chunk_id=page.page_id,
            page_number=page.page_number,
            cache_path=cache_path,
            status="cached",
            data=_read_json(cache_path),
            reused=True,
        )

    error_path = cache_path.with_suffix(".error.json")
    raw_text_path = cache_path.with_suffix(".invalid.txt")
    max_retries = max(1, int(config.get("max_retries", 1)))
    image_bytes = _preprocess_page(page, config)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            limiter.acquire()
            text, finish_reason = _call_gemini_text(
                api_key=api_key,
                model=str(config["model"]),
                image_bytes=image_bytes,
                prompt=prompt,
                known_header=known_header,
                timeout_seconds=int(config.get("timeout_seconds", 120)),
                max_output_tokens=int(config.get("max_output_tokens", 65535)),
            )
            data = _parse_jsonl(text, page=page, known_header=known_header)
            if finish_reason == "MAX_TOKENS":
                data["needs_review"] = True
                data["review_reason"] = "출력 토큰 한도 도달 — 페이지 하단 행 누락 가능. 원본 대조 필요."
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            _remove_if_exists(error_path)
            _remove_if_exists(raw_text_path)
            return VisionResult(
                chunk_id=page.page_id,
                page_number=page.page_number,
                cache_path=cache_path,
                status="ok",
                data=data,
            )
        except Exception as exc:  # noqa: BLE001 - 재시도/에러 기록 목적
            last_error = exc
            message = str(exc)
            if attempt < max_retries and not any(code in message for code in ("400", "401", "403")):
                delay = 30.0 if "429" in message else float(config.get("request_delay_seconds", 5)) * (2 ** (attempt - 1))
                if delay > 0:
                    time.sleep(delay)
                continue
            break

    error = {
        "page": page.page_number,
        "page_id": page.page_id,
        "status": "error",
        "message": str(last_error),
    }
    error_path.write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
    return VisionResult(
        chunk_id=page.page_id,
        page_number=page.page_number,
        cache_path=cache_path,
        status="error",
        data=None,
        error_path=error_path,
    )


def _preprocess_page(page: PageImage, config: dict[str, Any]) -> bytes:
    # 적응형 전처리: 표 영역 밝기를 분석해 그레이스케일 + 동적 대비/밝기를 적용한다.
    if not bool(config.get("adaptive_preprocess", True)):
        return page.image_path.read_bytes()
    try:
        from PIL import Image, ImageEnhance
    except ImportError:
        return page.image_path.read_bytes()

    image = Image.open(page.image_path).convert("L")
    width, height = image.size
    box = (int(width * 0.1), int(height * 0.15), int(width * 0.9), int(height * 0.5))
    sample = image.crop(box)
    histogram = sample.histogram()
    pixel_total = sum(histogram) or 1
    brightness = sum(i * count for i, count in enumerate(histogram)) / pixel_total

    if brightness < 85:
        contrast, bright = 1.8, 1.3
    elif brightness < 170:
        contrast, bright = 1.5, 1.1
    else:
        contrast, bright = 1.3, 1.0

    image = ImageEnhance.Contrast(image).enhance(contrast)
    image = ImageEnhance.Brightness(image).enhance(bright)

    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _call_gemini_text(
    api_key: str,
    model: str,
    image_bytes: bytes,
    prompt: str,
    known_header: list[str] | None,
    timeout_seconds: int,
    max_output_tokens: int,
) -> tuple[str, str]:
    header_hint = ""
    user_text = "값이 있는 컬럼만 헤더명을 키로 사용해 JSON Lines로 출력하세요. 첫 줄은 헤더 컬럼명 JSON 배열입니다."
    if known_header:
        header_hint = (
            "\n\n[중요] 이 페이지에는 표 헤더가 없을 수 있습니다. 반드시 아래 헤더명을 키로 사용하세요 "
            f"(임의 생성 금지):\n{json.dumps(known_header, ensure_ascii=False)}\n첫 줄 헤더 배열도 위 헤더 그대로 출력하세요."
        )
        user_text = (
            "값이 있는 컬럼만 헤더명을 키로 사용해 JSON Lines로 출력하세요. 첫 줄은 반드시 "
            f"{json.dumps(known_header, ensure_ascii=False)} 배열을 그대로 출력하세요."
        )

    payload = {
        "systemInstruction": {"parts": [{"text": prompt + header_hint}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_text},
                    {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(image_bytes).decode("ascii")}},
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "text/plain",
            "temperature": 0,
            "topP": 0.1,
            "maxOutputTokens": max_output_tokens,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc

    candidates = body.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini response has no candidates.")
    finish_reason = str(candidates[0].get("finishReason", "UNKNOWN"))
    if finish_reason in ("SAFETY", "PROHIBITED_CONTENT"):
        raise RuntimeError("Google AI가 이 이미지를 처리하지 못했습니다 (안전 필터 차단).")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    text = text.replace("```json", "").replace("```", "").strip()
    if not text:
        raise ValueError("Gemini 응답이 비어 있습니다.")
    return text, finish_reason


def _parse_jsonl(text: str, page: PageImage, known_header: list[str] | None) -> dict[str, Any]:
    header: list[str] | None = list(known_header) if known_header else None
    row_objects: list[dict[str, Any]] = []
    totals: list[dict[str, Any]] = []

    for line in text.split("\n"):
        line = line.strip()
        if not (line.startswith("{") or line.startswith("[")):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            if header is None and len(obj) >= 2 and all(isinstance(v, str) for v in obj):
                header = [str(v).strip() for v in obj]
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("__total") is True:
            value_text = str(obj.get("value", obj.get("amount", "")))
            totals.append(
                {
                    "label": str(obj.get("label", "")).strip() or "원본 합계",
                    "value_text": value_text,
                    "amount": _parse_amount(value_text),
                    "needs_review": False,
                    "review_reason": "",
                }
            )
            continue
        if obj.get("__skip") is True:
            continue
        row_objects.append(obj)

    if header is None:
        keys: list[str] = []
        for obj in row_objects:
            for key in obj.keys():
                if key not in ("__skip", "__total") and key not in keys:
                    keys.append(key)
        header = keys

    rows: list[dict[str, Any]] = []
    for index, obj in enumerate(row_objects, start=1):
        cells = [str(obj.get(col, "")).strip() for col in header]
        if all(cell == "" for cell in cells):
            continue
        rows.append(
            {
                "local_row_index": index,
                "cells": cells,
                "line_text": " ".join(cell for cell in cells if cell),
                "needs_review": False,
                "review_reason": "",
                "confidence_note": "",
            }
        )

    return {
        "schema_version": "1.0",
        "page": int(page.page_number),
        "chunk_id": page.page_id,
        "header": header,
        "rows": rows,
        "totals": totals,
        "needs_review": False,
        "review_reason": "",
        "notes": "",
    }


def _parse_amount(value_text: str) -> int | None:
    cleaned = str(value_text).replace(",", "").replace("원", "").strip()
    if not cleaned:
        return None
    negative = cleaned.startswith("-")
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits:
        return None
    amount = int(digits)
    return -amount if negative else amount


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()
