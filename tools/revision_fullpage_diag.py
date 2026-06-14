# 현대카드_8 결제원금 불일치 진단용 전체 페이지 Vision 재호출 도구
"""
현대카드_8의 pages 1-2(결제원금 71,240원 부족), pages 7-8(결제원금 16,500원 부족)
불일치 원인을 확인하기 위해 전체 페이지 이미지를 Gemini에 그대로 한 번 더 호출한다.

기존 청크 캐시는 페이지 하단/경계 행을 놓쳤을 가능성이 있어, 잘리지 않은 전체
페이지를 1회 1페이지 원칙으로 재호출해 누락 행 후보가 실제로 존재하는지 교차 확인한다.

이 도구는 파이프라인 캐시를 수정하지 않는다. 결과는 output/diag_hyundai_8/ 에만 쓴다.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from src.vision_extractor import (
    _call_gemini,
    _extract_text,
    _load_api_key,
    _load_prompt,
    _parse_json_text,
)


@dataclass
class FullPage:
    page_number: int
    chunk_id: str
    image_path: Path


def _call_one(page: FullPage, api_key: str, prompt: str, model: str, timeout: int) -> dict:
    full_prompt = (
        f"{prompt}\n\n"
        f"This is a FULL uncropped page image, not a partial chunk.\n"
        f"Extract every transaction row from top to bottom, including the last rows "
        f"just above any subtotal/total lines. Do not skip the bottom rows.\n\n"
        f"Chunk metadata:\n"
        f"- page: {page.page_number}\n"
        f"- chunk_id: {page.chunk_id}\n"
    )
    response = _call_gemini(
        api_key=api_key,
        model=model,
        image_path=page.image_path,
        prompt=full_prompt,
        timeout_seconds=timeout,
    )
    return _parse_json_text(_extract_text(response))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pages-dir",
        default="output/acceptance_hyundai_8/pages",
    )
    parser.add_argument("--out-dir", default="output/diag_hyundai_8")
    parser.add_argument(
        "--pages",
        default="1,2,7,8",
        help="확인할 페이지 번호 쉼표 구분.",
    )
    parser.add_argument("--model", default="gemini-3.1-flash-lite")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    pages_dir = Path(args.pages_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    api_key = _load_api_key({"api_key_env": "GEMINI_API_KEY"})
    prompt = _load_prompt(Path("prompts/vision_extract_table.md"))

    page_numbers = [int(p) for p in str(args.pages).split(",") if p.strip()]
    for page_number in page_numbers:
        image_path = pages_dir / f"page_{page_number:03d}.png"
        if not image_path.exists():
            print(f"[skip] no image: {image_path}")
            continue
        page = FullPage(
            page_number=page_number,
            chunk_id=f"page_{page_number:03d}_fullpage_diag",
            image_path=image_path,
        )
        print(f"[call] page {page_number} -> Gemini full page...")
        data = _call_one(page, api_key, prompt, args.model, args.timeout)
        out_path = out_dir / f"page_{page_number:03d}_fullpage.vision.json"
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = data.get("rows", [])
        totals = data.get("totals", [])
        print(f"  rows={len(rows)} totals={len(totals)} -> {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
