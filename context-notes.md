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
