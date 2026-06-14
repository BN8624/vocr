# 페이지 단위 추출기의 JSON Lines 파싱·헤더정렬·집계행 분리 회귀 테스트
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.page_extractor import _parse_jsonl, _parse_amount, page_pseudo_chunks
from src.page_renderer import PageImage


def _page(page_number: int = 1) -> PageImage:
    return PageImage(
        page_number=page_number,
        image_path=Path(f"page_{page_number:03d}.png"),
        width=2480,
        height=3505,
        dpi=300,
        reused=False,
    )


def main() -> int:
    # 헤더 배열 + 거래행(키 순서가 헤더와 달라도 헤더 순서로 정렬) + 집계행 + __skip
    text = "\n".join(
        [
            '["이용일","가맹점","이용금액","결제원금"]',
            '{"이용금액":"10,000","이용일":"01.12","가맹점":"노브랜드","결제원금":"10,000"}',
            '{"이용일":"01.13","가맹점":"택시","이용금액":"3,500"}',
            '{"__total": true, "label": "총 합계", "value": "13,500"}',
            '{"__skip": true, "이용일":"소계"}',
        ]
    )
    data = _parse_jsonl(text, page=_page(1), known_header=None)

    assert data["header"] == ["이용일", "가맹점", "이용금액", "결제원금"]
    assert len(data["rows"]) == 2
    # 객체 키 순서가 뒤섞여도 헤더 순서대로 cells가 정렬되어 열밀림이 없다
    assert data["rows"][0]["cells"] == ["01.12", "노브랜드", "10,000", "10,000"]
    # 빈 컬럼(결제원금)은 공백으로 채워 위치를 보존한다
    assert data["rows"][1]["cells"] == ["01.13", "택시", "3,500", ""]
    assert len(data["totals"]) == 1
    assert data["totals"][0]["label"] == "총 합계"
    assert data["totals"][0]["amount"] == 13500

    # 헤더 라인이 없고 knownHeader가 주입된 경우(2쪽~) 그 헤더로 정렬
    text2 = '{"가맹점":"카페","이용일":"01.14","이용금액":"5,000"}'
    data2 = _parse_jsonl(text2, page=_page(2), known_header=["이용일", "가맹점", "이용금액", "결제원금"])
    assert data2["header"] == ["이용일", "가맹점", "이용금액", "결제원금"]
    assert data2["rows"][0]["cells"] == ["01.14", "카페", "5,000", ""]

    # 금액 파싱
    assert _parse_amount("1,464,700") == 1464700
    assert _parse_amount("-18,000") == -18000
    assert _parse_amount("") is None

    # 페이지 의사 청크: 페이지 1장 = 청크 1개, chunk_id = page_NNN
    chunks = page_pseudo_chunks([_page(1), _page(2)])
    assert [c.chunk_id for c in chunks] == ["page_001", "page_002"]
    assert chunks[0].source_y_end == 3505

    print("page extractor test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
