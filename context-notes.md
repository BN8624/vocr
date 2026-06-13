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
- 정규화 이후 날짜/금액/청구금액 기준의 인접 청크 변형 중복 제거를 추가했다.
- 이미 안정적인 헤더가 있는 표에는 밀린 열 보정을 적용하지 않도록 제한했다.
- `청구할인 소계 -18,000`을 조정값으로 반영해 `amount_total_adjusted`가 `총합계 11,133,210`과 맞으면 자동 검산 일치로 처리한다.
- 포인트 사용 조정 행과 해외 이용 상세 행은 `amount`가 비어 있어도 정상 행으로 보아 검증/정규화 리뷰 false positive를 제거했다.
- 최종 `output/acceptance_hyundai_2` 결과는 `vision_ok=8`, `vision_errors=0`, `transaction_count=87`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, `matched_total=총합계 11,133,210`, `difference=0`이다.

## 2026-06-13 신한카드_1 정확도 100%

- 목표는 `신한카드_1.pdf`도 현대카드_2와 같은 기준으로 100% 정확도까지 올리는 것이다.
- 현재 작업공간 기준 `output/regression_samples/신한카드_1`에는 Vision 캐시가 없고, `output/acceptance_shinhan_1`도 아직 없다.
- 우선 `output/acceptance_shinhan_1`에 별도 산출물을 만들고, 캐시/검산/정규화/검증 지표를 확인한다.
- 최초 실행에서 totals 청크는 Gemini 503으로 실패했지만 재실행 후 `output/acceptance_shinhan_1` Vision 캐시는 4/4 성공 상태가 됐다.
- 본문 청크에는 `총합계 3,163,230` 후보가 이미 있었고, 실제 오류는 할부 청구 표의 `이용금액` 원거래 총액을 합산하면서 거래 합계가 6,401,302로 부풀어 오른 것이다.
- 문서화된 방향대로 issuer 전용 파서가 아니라 재사용 가능한 표 역할 보정으로 처리했다. 할부 청구 표에서 `원금/이번달 내실 금액 원금`을 검산 기준 `amount`로 쓰고, `이용금액`과 `결제 후 잔액`은 원본 보조 필드로 남긴다.
- 신한 문서의 `24.11.13` 같은 `YY.MM.DD` 날짜는 정상 날짜로 보고 `2024-11-13`처럼 정규화한다.
- `12전기1702487618`, `12수신료3473966375`처럼 공과금명과 관리번호가 결합된 가맹점은 숫자 오염 false positive에서 제외한다. 숫자만 있는 오염 가맹점 검증은 유지한다.
- 최종 `output/acceptance_shinhan_1` 결과는 `vision_ok=4`, `vision_errors=0`, `transaction_count=47`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, `matched_total=총합계 3,163,230`, `difference=0`이다.
- 현재 코드에는 `merged/automation_summary.json` 생성 경로가 없어 해당 파일은 생성되지 않았다. 이번 작업은 정확도 지표와 검산 자동 일치 개선에 한정했다.

## 2026-06-13 신한카드_3 정확도 100%

- 목표는 `신한카드_3.pdf`를 100% 정확도까지 올리는 것이다.
- 사용자 경험상 Gemini 3.1 Flash Lite는 2장을 넘기면 환각 위험이 있으므로, 다중 페이지 PDF는 호출 1회당 1페이지 이하만 넣는 원칙으로 실행한다.
- 현재 `src/vision_extractor.py`는 `_call_gemini()`에 `image_path` 하나만 전달하고, `src/chunk_builder.py`는 페이지별 `page_001_chunk_01` 같은 단일 페이지 청크 이미지를 만든다. 따라서 한 호출에 여러 페이지가 섞이지 않는다.
- `신한카드_3.pdf`는 3페이지이며 기본 설정 기준 본문 청크 9개와 합계 청크 3개, 총 12개 Vision 호출 대상이 생성된다.
- 산출물은 기존 결과와 분리해 `output/acceptance_shinhan_3`에 만든다.
- 최초 호출에서 `page_003_chunk_02`가 Gemini 503으로 실패했다. 동일 산출물을 재실행하니 기존 11개 캐시는 재사용되고 실패 청크만 재호출되어 12/12 캐시 성공 상태가 됐다.
- 검증 이슈는 0건이었지만 page 2 거래 합계가 원본 `총합계 2,771,170`보다 22,500 컸다. 원인은 `page_002_chunk_02` 첫 행의 `04.11.00 / 쿠판 / 22,500` 환각 행이었다.
- `04.11.00`처럼 달력상 불가능한 날짜는 정규화 대상 거래에서 제외하고, 검증기에서도 날짜 형식뿐 아니라 실제 날짜 유효성을 확인하도록 했다.
- 다중 페이지 명세서에서는 각 페이지의 `총합계` 후보가 개별 값으로만 존재한다. `총합계`처럼 같은 합계 라벨이 여러 페이지에서 반복되면 합산 후보를 만들어 `amount_total`과 자동 비교하도록 했다.
- 최종 `output/acceptance_shinhan_3` 결과는 `vision_ok=12`, `vision_errors=0`, `transaction_count=141`, `normalization_review_count=0`, `invalid_date_excluded_count=1`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, `matched_total=총합계 합산 8,594,250`, `difference=0`이다.

## 2026-06-13 신한카드_3 후속 검증

- totals 전용 Vision 청크는 검산 후보로만 써야 하므로, 응답에 우발적으로 `rows`가 들어와도 `row_merger`가 거래 원천 행으로 수집하지 않도록 했다.
- `tests/test_total_chunks.py`에 totals 청크 응답의 `rows`가 `raw_row_count == 0`으로 제외되는 회귀 검증을 추가했다.
- `python main.py --input "견본\신한카드_3.pdf" --output output\acceptance_shinhan_3`를 캐시 기반으로 재실행했다. 결과는 `llm_calls=0`, `vision_ok=12`, `transaction_count=141`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, `normalized_amount_total=8594250`로 유지됐다.
- 관련 테스트 `python tests/test_total_chunks.py`, `python tests/test_checksum_selection.py`, `python tests/test_profile_signature.py`가 통과했다.
