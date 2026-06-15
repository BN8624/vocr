## 2026-06-15 추가 계획: 원본표 복원 파이프라인을 메인 산출물로 전환

이번 전환의 성공 기준은 다음이다.

```text
검산이 맞는다.
AND result.xlsx가 생성된다.
AND 첫 번째 시트가 원본표다.
AND 원본표에 PDF의 모든 행과 열이 최대한 그대로 들어간다.
AND 정규화/검산 시트는 보조 자료로 뒤에 붙는다.
```

작업 순서는 다음과 같다.

```text
1. src/excel_exporter.py에서 rows_merged.jsonl 기반 원본표 시트 생성 함수를 추가한다.
   검증은 raw.header와 raw.cells가 Excel에 그대로 들어가는 테스트로 한다.
2. export_excel()이 source_rows_path를 실제로 사용해 원본표를 첫 번째 시트로 만든다.
   검증은 result.xlsx 첫 번째 시트명이 원본표인지 확인한다.
3. 기존 전체명세 시트를 전체명세_정규화로 이름 변경한다.
   검증은 기존 검산, 원본셀, 추가필드, 확인필요 시트가 유지되는지 확인한다.
4. tests/test_original_table_export.py를 추가하고 regression_samples.py PASS 조건을 강화한다.
   검증은 새 테스트와 기존 Excel exporter 테스트를 함께 실행한다.
5. app.py 경로로 생성되는 result.xlsx도 같은 시트 계약을 만족하는지 확인한다.
   검증은 캐시 기반 실사용 샘플로 workbook sheet order를 확인한다.
```

검산은 품질 보증 장치고, 실제 작업은 원본표 복원이다.

---

맞습니다. 이 말이 핵심입니다.

지금부터 vocr의 목표는 이렇게 잡아야 합니다.

> **프로젝트 폴더에 있는 3개 카드사의 로컬 명세서를 1장부터 시작해 여러 장 샘플까지 자동으로 Excel 변환한다.**

그리고 `review.html`은 “사람이 많이 검토하는 화면”이 아니라 **자동 변환 실패 원인을 찾는 디버그 화면**이어야 합니다. GitHub README도 현재 흐름을 `PDF 이미지화 → 청크 생성 → Vision LLM JSON 추출 → 행 병합 → 열 매핑 → 정규화 → 검증 → Excel export`로 잡고 있고, `result.xlsx`, `review.html`, 검증 결과, 매핑 프로필 재사용까지 이미 구현 대상으로 명시되어 있습니다. ([GitHub][1]) 또 README에는 견본 PDF 파일명 끝 숫자를 기대 페이지 수로 보고 `tests/regression_samples.py`로 전체 견본 회귀 리포트를 남기는 구조가 설명되어 있습니다. ([GitHub][1])

다만 공개 GitHub 기준으로는 견본 PDF가 로컬 테스트용이고 GitHub에는 올리지 않는다고 되어 있어서, 제가 실제 명세서 이미지를 직접 본 건 아닙니다. 그래서 아래 지시서는 **현재 프로젝트 폴더에 이미 들어가 있는 3개 카드사 샘플을 acceptance set으로 삼으라**는 방식으로 작성했습니다. ([GitHub][1])

# vocr 자동 Excel 변환 작업지시서 v0.4

## 0. 목표 재정의

vocr의 목표는 “사람이 검토해서 고치는 카드 명세서 변환기”가 아니다.

목표는 다음이다.

> 프로젝트 폴더에 있는 3개 카드사의 카드 명세서를 사람 개입 없이 자동으로 Excel 변환한다.

현재 프로젝트 폴더에는 카드사별로 다음 샘플이 준비되어 있다.

```text
카드사 A:
  1장 명세서
  2장 또는 3장 명세서
  여러 장 명세서

카드사 B:
  1장 명세서
  2장 또는 3장 명세서
  여러 장 명세서

카드사 C:
  1장 명세서
  2장 또는 3장 명세서
  여러 장 명세서
```

이 로컬 견본 샘플은 단순 테스트 자료가 아니라 vocr의 1차 합격 기준이다.

---

# 1. 핵심 성공 기준

## 1-1. 최종 성공 기준

다음 명령으로 프로젝트 폴더의 모든 견본 명세서를 실행했을 때, 모든 샘플에서 Excel이 자동 생성되어야 한다.

```bash
python tests/regression_samples.py --with-vision
```

각 샘플마다 다음 산출물이 생성되어야 한다.

```text
output/<sample_name>/
  review.html
  result.xlsx
  summary.json
  merged/
    rows_raw.jsonl
    rows_merged.jsonl
    transactions.jsonl
    transactions_validated.jsonl
    validation_summary.json
    automation_summary.json
```

단, 성공 기준은 `result.xlsx` 생성만이 아니다.

각 샘플은 다음 조건을 만족해야 한다.

```text
1. PDF 페이지 수가 기대값과 일치한다.
2. 모든 페이지에서 거래 행이 추출된다.
3. result.xlsx가 생성된다.
4. 전체명세 시트가 비어 있지 않다.
5. 원본셀 시트가 생성된다.
6. 검산 시트가 생성된다.
7. 확인필요 시트가 생성된다.
8. automation_summary.json이 생성된다.
9. 자동 확정률이 계산된다.
10. 수동 검토율이 계산된다.
11. hard review 건수가 계산된다.
12. blocked 상태가 없어야 한다.
```

---

# 2. 프로젝트 철학

## 2-1. review.html의 역할

`review.html`은 사용자가 모든 행을 검토하기 위한 화면이 아니다.

`review.html`의 역할은 다음이다.

```text
자동 변환 실패 원인 확인
자동 확정률 확인
검산 실패 원인 확인
매핑 실패 원인 확인
중복 처리 실패 원인 확인
다음 실행 개선을 위한 디버그
```

즉, 사람이 매번 표 전체를 훑어봐야 한다면 실패다.

## 2-2. needs_review의 의미

`needs_review`는 안전장치이지만 동시에 자동화 실패 신호다.

다음처럼 판단한다.

```text
needs_review 0~5%:
  좋음. 자동화 가치 있음.

needs_review 5~10%:
  허용 가능. 원인 분석 후 개선 필요.

needs_review 10~30%:
  자동화 품질 부족. 프로필/청크/정규화 개선 필요.

needs_review 30% 이상:
  실패. 사람이 검토하는 도구에 가까움.
```

## 2-3. 목표 지표

1차 목표:

```text
현재 로컬 견본 샘플 전부 result.xlsx 자동 생성
blocked 샘플 0개
hard_review_rate <= 5%
manual_review_rate <= 15%
```

2차 목표:

```text
hard_review_rate <= 3%
manual_review_rate <= 10%
```

최종 목표:

```text
hard_review_rate <= 1%
manual_review_rate <= 5%
silent_error_count == 0
```

---

# 3. P0: 로컬 견본 샘플을 acceptance set으로 고정

## P0-1. 샘플 목록 자동 인식

현재 프로젝트 폴더의 샘플 PDF를 자동 탐색한다.

대상 폴더:

```text
samples/
```

샘플 파일명 규칙은 기존 README 정책을 유지한다.

예:

```text
삼성카드_1.pdf
삼성카드_2.pdf
삼성카드_5.pdf
삼성카드_7.pdf
신한카드_1.pdf
신한카드_3.pdf
신한카드_11.pdf
현대카드_1.pdf
현대카드_2.pdf
현대카드_8.pdf
```

숫자가 있는 파일은 기대 페이지 수로 사용한다.

```text
*_1.pdf => expected_pages = 1
*_3.pdf => expected_pages = 3
```

`여러장`, `multi`, `many` 같은 이름은 페이지 수를 PDF에서 직접 읽고 기록한다.

## P0-2. sample_manifest.json 자동 생성

다음 파일을 생성한다.

```text
samples/sample_manifest.json
```

형식:

```json
[
  {
    "sample_id": "samsung_1",
    "issuer": "samsung",
    "path": "samples/삼성카드_1.pdf",
    "expected_pages": 1,
    "sample_type": "single_page"
  },
  {
    "sample_id": "samsung_2",
    "issuer": "samsung",
    "path": "samples/삼성카드_2.pdf",
    "expected_pages": 2,
    "sample_type": "two_pages"
  },
  {
    "sample_id": "samsung_multi",
    "issuer": "samsung",
    "path": "samples/삼성카드_여러장.pdf",
    "expected_pages": null,
    "sample_type": "multi_page"
  }
]
```

수동 작성도 가능해야 하지만, 기본은 자동 생성이다.

추가 도구:

```text
tools/build_sample_manifest.py
```

명령:

```bash
python tools/build_sample_manifest.py --samples samples --output samples/sample_manifest.json
```

---

# 4. P0: 전체 샘플 자동 변환 리포트

## P0-3. regression_samples.py를 acceptance runner로 강화

`tests/regression_samples.py`는 단순 smoke test가 아니라 로컬 견본 샘플 자동 변환 합격 판정기로 바꾼다.

실행 명령:

```bash
python tests/regression_samples.py --with-vision
```

기본 dry-run도 유지한다.

```bash
python tests/regression_samples.py
```

dry-run은 페이지 렌더링, 청크 생성, review.html 구조 생성만 확인한다.

with-vision은 실제 Gemini Vision API까지 호출해서 자동 Excel 변환을 확인한다.

## P0-4. 샘플별 리포트 생성

다음 파일을 생성한다.

```text
output/regression_samples/sample_regression_report.json
output/regression_samples/sample_regression_report.md
```

각 샘플별로 다음 항목을 기록한다.

```json
{
  "sample_id": "samsung_2",
  "issuer": "samsung",
  "path": "samples/삼성카드_2.pdf",
  "expected_pages": 2,
  "actual_pages": 2,
  "page_count_status": "matched",
  "chunk_count": 12,
  "vision_success_count": 12,
  "vision_fail_count": 0,
  "raw_row_count": 86,
  "representative_row_count": 74,
  "transaction_count": 72,
  "duplicate_excluded_count": 14,
  "result_xlsx_created": true,
  "review_html_created": true,
  "checksum_status": "matched",
  "auto_confirmed": 69,
  "auto_confirmed_with_warning": 2,
  "needs_light_review": 1,
  "needs_hard_review": 0,
  "blocked": 0,
  "auto_accept_rate": 0.986,
  "manual_review_rate": 0.014,
  "hard_review_rate": 0.0,
  "pass": true,
  "fail_reasons": []
}
```

## P0-5. 전체 합격 기준

로컬 견본 샘플 전체에 대해 다음 조건을 만족해야 한다.

```text
모든 PDF 페이지 렌더링 성공
모든 PDF 청크 생성 성공
모든 PDF Vision 추출 성공
모든 PDF result.xlsx 생성 성공
모든 PDF review.html 생성 성공
blocked 샘플 0개
blocked row 0개
hard_review_rate 평균 <= 5%
manual_review_rate 평균 <= 15%
```

한 샘플이라도 실패하면 전체 실패다.

---

# 5. P0: 자동화 품질 요약 추가

## P0-6. automation_summary.json 추가

각 output 폴더에 다음 파일을 생성한다.

```text
merged/automation_summary.json
```

내용:

```json
{
  "sample_id": "samsung_3",
  "issuer": "samsung",
  "row_count": 72,
  "auto_confirmed": 69,
  "auto_confirmed_with_warning": 2,
  "needs_light_review": 1,
  "needs_hard_review": 0,
  "blocked": 0,
  "auto_accept_rate": 0.986,
  "manual_review_rate": 0.014,
  "hard_review_rate": 0.0,
  "top_review_reasons": [
    {
      "reason": "중복 후보",
      "count": 1
    }
  ],
  "profile_reuse": {
    "profile_applied": true,
    "profile_name": "samsung_card_v1",
    "match_type": "layout_signature",
    "confidence": 0.98
  },
  "checksum": {
    "status": "matched",
    "source": "auto_selected",
    "expected_total": 1234567,
    "actual_total": 1234567
  }
}
```

---

# 6. P1: 행 상태 세분화

현재 단순 `needs_review`만으로는 사람이 너무 많이 봐야 한다.

행 상태를 다음처럼 나눈다.

```text
auto_confirmed
auto_confirmed_with_warning
needs_light_review
needs_hard_review
blocked
```

## 6-1. 상태 의미

```text
auto_confirmed:
  바로 Excel 전체명세에 사용한다.

auto_confirmed_with_warning:
  Excel에는 사용하되 경고만 남긴다. 사람이 반드시 볼 필요는 없다.

needs_light_review:
  사람이 보면 좋지만 전체 변환을 막지는 않는다.

needs_hard_review:
  핵심 필드가 불확실하다. 자동 변환 품질 저하로 기록한다.

blocked:
  해당 행 또는 샘플은 자동 변환 실패다.
```

## 6-2. 행별 automation 필드 추가

`transactions_validated.jsonl` 각 행에 다음을 추가한다.

```json
{
  "automation": {
    "row_status": "auto_confirmed",
    "confidence_score": 0.97,
    "risk_level": "low",
    "signals": {
      "date_valid": true,
      "merchant_valid": true,
      "amount_valid": true,
      "billing_amount_valid": true,
      "profile_match": "exact",
      "duplicate_status": "unique",
      "checksum_context": "matched",
      "column_quality": "stable"
    },
    "reasons": []
  }
}
```

---

# 7. P1: 카드사별 프로필을 자동화 엔진으로 사용

## 7-1. 목표

3개 카드사의 1장 / 2장 또는 3장 / 여러 장 명세서는 반복 양식이다.

따라서 한 번 안정화된 카드사 양식은 다음 실행부터 자동으로 처리되어야 한다.

## 7-2. 프로필 저장 정보 확장

프로필에 다음 정보를 저장한다.

```json
{
  "profile_version": "2.0",
  "issuer": "samsung",
  "layout_signature": "...",
  "header_signature": "...",
  "column_count": 8,
  "column_roles": {
    "col_1": "date",
    "col_2": "card_label",
    "col_3": "merchant",
    "col_4": "amount",
    "col_5": "billing_amount"
  },
  "value_patterns": {
    "date": "MM-DD",
    "amount": "KRW_INTEGER",
    "billing_amount": "KRW_INTEGER",
    "merchant": "KOREAN_TEXT"
  },
  "verified_samples": [
    "samsung_1",
    "samsung_3",
    "samsung_multi"
  ],
  "last_verified_metrics": {
    "auto_accept_rate": 0.97,
    "manual_review_rate": 0.03,
    "hard_review_rate": 0.0,
    "silent_error_count": 0
  }
}
```

## 7-3. 프로필 승격 조건

카드사별 프로필은 다음 조건을 만족하면 stable profile로 승격한다.

```text
같은 카드사의 1장 샘플 통과
같은 카드사의 2장 또는 3장 샘플 통과
같은 카드사의 여러 장 샘플 통과
blocked row 0개
hard_review_rate <= 3%
manual_review_rate <= 10%
silent_error_count == 0
```

stable profile이 된 카드사는 다음 실행부터 자동 확정률을 높이는 데 사용한다.

---

# 8. P1: 검산 후보 자동 선택

사람이 검산 기준 합계를 매번 선택해야 하면 자동 변환이 아니다.

## 8-1. 목표

명세서 안의 합계 후보 중 기준 합계를 자동 선택한다.

## 8-2. 합계 후보 점수화

각 합계 후보에 점수를 부여한다.

```json
{
  "candidate_text": "이번달 청구금액",
  "amount": 1234567,
  "score": 0.96,
  "signals": {
    "keyword": "청구금액",
    "position": "summary_area",
    "page": "last_page",
    "matches_transaction_sum": true,
    "issuer_profile_match": true
  }
}
```

## 8-3. 자동 선택 조건

```text
score >= 0.90
거래 합계와 일치 또는 허용 오차 내
합계 후보 간 충돌 없음
카드사 프로필에서 해당 합계 라벨이 검증됨
```

성공 시:

```text
checksum_source = auto_selected
```

실패 시에만 사람이 선택한다.

---

# 9. P1: 중복 처리 자동화

겹침 청크에서 같은 거래가 반복 추출되는 것은 정상이다.

목표는 다음이다.

```text
명백한 중복은 자동 제외
애매한 반복 결제는 유지
충돌만 예외로 표시
```

## 9-1. 중복 상태

```text
unique
duplicate_exact_excluded
duplicate_fuzzy_auto_excluded
duplicate_candidate_light_review
duplicate_conflict_hard_review
```

## 9-2. 자동 제외 조건

다음 조건을 모두 만족하면 자동 제외한다.

```text
같은 페이지
인접 청크
날짜 동일
금액 동일
가맹점명 유사도 높음
카드명 동일 또는 공백
겹침 영역에서 나온 행
```

## 9-3. 자동 제외 금지 조건

다음 경우는 자동 제외하지 않는다.

```text
같은 날짜 + 같은 금액 + 다른 가맹점
같은 날 같은 금액 반복 결제 가능성
가맹점명이 비어 있음
금액 후보가 충돌함
```

---

# 10. P1: strict parser + 자동 복구

정확도를 높이려면 금액/날짜/가맹점 파싱이 엄격해야 한다.

하지만 파서가 엄격해져서 사람이 볼 행이 폭증하면 안 된다.

## 10-1. 필드별 파서 분리

`normalizer.py`에 다음 파서를 둔다.

```text
parse_date()
parse_krw_amount()
parse_billing_amount()
parse_installment_month()
parse_points()
parse_foreign_amount()
parse_exchange_rate()
parse_approval_number()
```

## 10-2. 자동 복구 순서

파싱 실패 시 바로 `needs_hard_review`로 보내지 않는다.

다음 순서로 자동 복구한다.

```text
1. 같은 row의 다른 후보 값 확인
2. 같은 column의 주변 row 패턴 확인
3. 카드사 stable profile의 value pattern 확인
4. 합계 검산과 대조
5. 그래도 불확실하면 needs_hard_review
```

---

# 11. P1: 선택적 2-pass Vision

모든 청크를 두 번 읽으면 비용이 증가한다.

따라서 위험한 청크만 2-pass로 재질문한다.

## 11-1. 2-pass 조건

```text
JSON 파싱 실패
거래 행 수가 주변 청크와 크게 다름
금액 열이 흔들림
잘린 행 의심
중복 충돌 발생
검산 불일치 발생
hard_review 행이 많은 청크
```

## 11-2. 병합 규칙

```text
두 결과가 같음:
  confidence 상승

금액/날짜는 같고 가맹점만 약간 다름:
  더 자연스러운 텍스트 선택 + warning

금액이 다름:
  hard_review

행 개수가 다름:
  chunk_conflict_hard_review

한쪽만 JSON 정상:
  정상 결과 사용 + warning
```

---

# 12. P2: review.html을 예외 처리 화면으로 축소

`review.html`의 첫 화면은 전체 표가 아니라 자동 변환 결과 요약이어야 한다.

## 12-1. 첫 화면 표시 항목

```text
전체 샘플명
카드사
페이지 수
거래 행 수
자동 확정률
수동 검토율
hard review 건수
blocked 건수
검산 상태
프로필 적용 상태
Excel 생성 상태
```

## 12-2. 기본적으로 숨길 항목

```text
auto_confirmed 행
auto_confirmed_with_warning 행
```

## 12-3. 먼저 보여줄 항목

```text
blocked 행
needs_hard_review 행
검산 불일치
중복 충돌
프로필 충돌
금액 후보 충돌
```

---

# 13. P2: 문서와 리포트 정리

## 13-1. STATUS.md 추가

```text
STATUS.md
```

형식:

```text
기능 | 상태 | 근거 파일 | 자동화 기여도 | 남은 문제
```

상태값:

```text
DONE
PARTIAL
PLANNED
BROKEN
NEEDS_VERIFICATION
```

## 13-2. TEST_REPORT.md 추가

```text
TEST_REPORT.md
```

포함 내용:

```text
샘플 수
카드사 수
1장 샘플 결과
2장/3장 샘플 결과
여러 장 샘플 결과
auto_accept_rate 평균
manual_review_rate 평균
hard_review_rate 평균
blocked 수
실패 원인 TOP 10
지난 실행 대비 개선/악화
```

---

# 14. 완료 기준

이번 작업은 다음 명령이 통과해야 완료로 본다.

```bash
python tools/build_sample_manifest.py --samples samples --output samples/sample_manifest.json
python -m pytest -q
python tests/regression_samples.py
python tests/regression_samples.py --with-vision
```

그리고 다음 조건을 만족해야 한다.

```text
3개 카드사 전체 샘플 인식
1장 / 2장 또는 3장 / 여러 장 샘플 구분
모든 샘플 result.xlsx 자동 생성
모든 샘플 review.html 자동 생성
모든 샘플 automation_summary.json 생성
sample_regression_report.json 생성
sample_regression_report.md 생성
blocked 샘플 0개
blocked row 0개
hard_review_rate 평균 <= 5%
manual_review_rate 평균 <= 15%
```

---

# 15. 하지 말 것

이번 작업에서 하지 않는다.

```text
서버 보안 작업
카드사별 완전 하드코딩 파서로 도망가기
OCR-first 구조로 회귀
사람이 모든 행을 검토하는 UI 강화
확인필요 행을 많이 남기는 방식으로 책임 회피
result.xlsx 생성만 성공으로 처리
검산 기준을 매번 사람이 선택하게 방치
Vision 프롬프트만 고치고 측정 없이 감으로 판단
```

---

# 16. 최우선 작업 순서

```text
1. samples/sample_manifest.json 생성 도구 추가
2. regression_samples.py를 로컬 견본 acceptance runner로 강화
3. automation_summary.json 추가
4. row_status / confidence_score / risk_level 추가
5. 카드사별 stable profile 승격 기준 추가
6. 검산 후보 자동 선택 추가
7. 중복 처리 상태 세분화
8. strict parser + 자동 복구 추가
9. 선택적 2-pass Vision 추가
10. review.html을 예외 처리 화면으로 축소
11. STATUS.md / TEST_REPORT.md 추가
```

가장 먼저 할 일은 변환 알고리즘 수정이 아니다.

가장 먼저 할 일은 현재 프로젝트 폴더의 3개 카드사 견본이 1장부터 단계적으로 자동 통과하는지, 실패한다면 어느 단계에서 실패하는지 숫자로 드러내는 것이다.

[1]: https://github.com/BN8624/vocr "GitHub - BN8624/vocr · GitHub"
