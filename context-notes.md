# Context Notes

## 2026-06-13 현대카드_1 정확도 개선

- 요청 범위는 `현대카드_1`의 캐시 4/4 성공 이후 정확도 개선이다.
- 우선순위는 합계 후보 오류와 `validation_issues.json` 27건 분석이다.
- 현재 가정은 `output/acceptance_hyundai_1`가 최신 캐시 성공 실행 산출물이라는 것이다.
- 성공 기준은 합계 후보 오류 원인을 확인하고, 자동 처리 가능한 검증 이슈를 줄인 뒤 관련 테스트와 캐시 재실행 결과를 보고하는 것이다.
- 확인 결과 잘못된 합계 후보 4개는 실제 합계가 아니라 하단 `M포인트사용` 거래성 행이었다.
- `card_label_merchant_like` 25건은 `본인 the Purple(KAL)` 같은 정상 카드명을 긴 텍스트라는 이유로 가맹점처럼 오판한 false positive였다.
- 남은 `merchant_mostly_numeric` 4건은 택시 번호가 포함된 정상 가맹점명이었고, `amount_not_numeric` 1건은 금액을 만들면 안 되는 포인트 사용 조정 행이었다.
- `src/validator.py`에서 거래성 포인트 행을 합계 후보에서 제외하고, 카드명과 택시 가맹점 및 혜택 조정 행을 검증 false positive로 처리하지 않도록 좁게 수정했다.
- 캐시 기반 `현대카드_1` 재실행 결과는 `vision_ok=4`, `vision_errors=0`, `validation_issue_row_count=0`, `checksum_status=no_source_total`, `source_total_candidates=0`이다.

## 2026-06-13 현대카드_2 합계 후보 확인

- 계획을 변경해 `현대카드_2.pdf`를 기준으로 합계가 있는 명세서에서 검산 후보가 제대로 잡히는지 확인한다.
- 기존 `output/regression_samples/현대카드_2` 산출물이 있으나, 이번 작업은 비교가 쉽도록 `output/acceptance_hyundai_2`에 별도 생성한다.
- 성공 기준은 실제 합계 후보가 `source_total_candidates`에 남고, 잘못된 거래성 후보는 제외되며, 관련 테스트와 캐시 기반 재실행 결과를 보고하는 것이다.
- 사용자가 샌드박스 밖에서 API 호출을 실행했고, `output/acceptance_hyundai_2` 기준 Vision 캐시는 8/8 성공했다.
- 확인 결과 `총합계 11,133,210` 후보가 `source_total_candidates`에 들어왔다.
- 잘못된 `M포인트사용 할인` 후보는 후보 필터 보강 후 제거됐다.
- `해외이용금액`이 원화 `amount`로 들어가는 문제를 막기 위해 해외 금액, 접수금액, 환율 헤더를 별도 필드로 분리했다.
- `이용내용`처럼 카드명/가맹점/금액 열이 한 칸 밀려 들어온 표를 값 패턴으로 보정하는 매핑 규칙을 추가했다.
- 재실행 결과는 `vision_ok=8`, `vision_errors=0`, `source_total_candidates=4`, `checksum_status=no_user_total_selected`, `amount_total=12,954,184`, `billing_amount_total=12,590,780`, `validation_issue_row_count=8`이다.
- 아직 `총합계 11,133,210`과 거래 합계가 맞지 않는다. 원인은 `page_002_chunk_01`과 `page_002_chunk_02`의 변형 중복이 exact duplicate로 제거되지 않는 점이 크다.
