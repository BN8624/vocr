# vocr

Image-based Korean credit card statement PDFs를 Vision LLM으로 읽고, 사람이 검토할 수 있는 `review.html`과 감사 가능한 Excel 파일로 변환하는 로컬 Python 도구입니다.

이 프로젝트는 OCR-first 방식이 아닙니다. 기본 흐름은 `PDF 이미지화 -> 청크 생성 -> Vision LLM JSON 추출 -> 행 병합 -> 열 매핑 -> 정규화 -> 검증 -> Excel export`입니다.

## 현재 상태

구현된 주요 기능:

- PDF 페이지를 고해상도 PNG로 렌더링
- 헤더가 붙은 겹침 청크 이미지 생성
- Gemini Vision API 호출 및 응답 캐시
- `review.html` 생성
- 원본 row/cell 보존
- 겹침 청크 중복 후보 표시
- 열 매핑 추천 및 iPhone 친화 UI
- 매핑 프로필 다운로드, PC 저장, 재사용
- 거래 정규화
- 검증 결과 생성
- `result.xlsx` export

## 중복 행 처리

겹침 청크에서 같은 거래가 반복 추출되는 것은 정상입니다. `row_merger.py`는 같은 페이지의 동일한 raw cells가 서로 다른 청크에서 반복되면 대표행 1개를 `representative`로 정하고, 나머지는 `duplicate_excluded`로 표시합니다.

- `representative`: 거래 정규화, 검산, `전체명세` 시트에 사용
- `duplicate_excluded`: 거래 합계에서는 제외, `원본셀` 시트에는 보존
- 애매한 경우: 삭제하지 않고 `needs_review`로 남기는 방향 유지

이렇게 해서 원본 보존과 합계 오염 방지를 같이 지킵니다.

## 설치

```bash
pip install -r requirements.txt
```

Gemini API 키는 환경변수 또는 로컬 `.env`에 넣습니다. 둘 중 하나면 됩니다.

```text
GEMINI_API_KEY=your_key_here
GOOGLE_API_KEY=your_key_here
```

`.env`, `output/`, 견본 PDF, 저장된 매핑 프로필 JSON은 GitHub에 올라가지 않도록 무시됩니다.

## 기본 실행

API 호출 없이, 이미 캐시된 결과만 재사용하거나 페이지/청크/review만 만들려면:

```bash
python main.py --input samples/card.pdf --output output --dry-run
```

Vision API까지 호출하려면:

```bash
python main.py --input samples/card.pdf --output output
```

API smoke test처럼 앞 청크 일부만 호출하려면:

```bash
python main.py --input samples/card.pdf --output output --limit-chunks 1
```

캐시를 무시하고 페이지/청크를 다시 만들려면 `--force`, Vision 응답을 다시 받으려면 `--force-vision`을 사용합니다.

## iPhone에서 검토

단순히 보기만 할 때는 정적 파일 서버로도 충분합니다. 하지만 매핑을 PC의 `profiles/` 폴더에 바로 저장하려면 전용 리뷰 서버를 사용합니다.

```bash
python serve_review.py --host 0.0.0.0 --port 8012
```

Tailscale로 접속할 때:

```text
http://<tailscale-ip>:8012/output/review.html
```

예시 출력 폴더가 `output/gemini_smoke`라면:

```text
http://<tailscale-ip>:8012/output/gemini_smoke/review.html
```

포트 `8000`, `8400`은 다른 용도로 사용 중이면 피하세요. 현재 작업에서는 `8012`를 저장 가능한 리뷰 서버 포트로 사용합니다.

## 매핑 프로필

`review.html`의 열 매핑 영역에는 두 버튼이 있습니다.

- `PC에 매핑 저장`: `serve_review.py` 서버가 실행 중일 때 PC의 `profiles/` 폴더에 저장
- `매핑 JSON 내려받기`: 서버가 없을 때 브라우저 다운로드로 저장

저장된 `profiles/*.json`은 다음 실행부터 자동 적용됩니다.

특정 프로필을 명시적으로 적용할 수도 있습니다.

```bash
python main.py --input samples/card.pdf --output output --dry-run --mapping-profile profiles/mapping-profile.json
```

프로필은 힌트일 뿐입니다. 원본 셀은 계속 보존되고, 검증에서 의심되는 행은 `확인필요`로 남습니다.

## 출력 파일

주요 산출물:

```text
output/
  pages/
  chunks/
  cache/
  merged/
    rows_raw.jsonl
    rows_merged.jsonl
    mapping_suggestions.json
    transactions.jsonl
    transactions_validated.jsonl
    normalization_summary.json
    validation_summary.json
    validation_issues.json
  review.html
  result.xlsx
  summary.json
```

Excel 시트:

- `전체명세`
- `검산`
- `원본셀`
- `추가필드`
- `확인필요`

불확실한 행은 삭제하거나 숨기지 않습니다.

## 검증 상태

검산 상태는 다음처럼 구분합니다.

- `검산 일치`: 추출 합계와 원본 합계 후보가 일치
- `검산 불일치`: 전체 청크를 봤지만 합계가 맞지 않음
- `원본 합계 없음`: 전체 청크를 봤지만 원본 합계 후보를 찾지 못함
- `합계 확인 미완료`: 일부 청크만 Vision 결과가 있어 다음 페이지/청크의 합계를 아직 못 봤을 수 있음

## 견본 테스트

견본 PDF 파일명 끝의 숫자는 기대 페이지 수입니다. 예를 들어 `삼성카드_3.pdf`는 3페이지여야 합니다.

```bash
python tests/smoke_phase1_samples.py
```

견본 PDF는 로컬 테스트용이며 GitHub에 올리지 않습니다.
