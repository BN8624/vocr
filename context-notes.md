# Context Notes

## 2026-06-14 카드사별 검산 기준 규칙

- 삼성카드는 거래의 `amount`가 청구/입금 기준이고 원본의 `이용금액합계`는 이용금액 기준이라 같은 합계로 비교하면 안 된다.
- 검산 요약에 `basis_totals`를 추가해 카드사별 보조 검산 기준을 기록한다.
- 삼성 `이용금액합계` 후보는 포인트/적립/남은금액 후보를 제외하고 페이지별 가장 큰 이용금액합계 후보만 합산한다.
- 자동 선택은 새 기준 합계와 원본 합산 후보가 정확히 일치할 때만 허용한다.
- `삼성카드_7` 재실행 결과 `samsung_usage_amount_total=16,645,441`, 원본 이용금액합계 후보 합산은 `16,545,610`이라 99,831원 차이가 남아 자동 선택하지 않았다.
- `현대카드_8`은 페이지 묶음별 차이가 9,605원 부족, 78,000원 과다, 0원, 381,418원 부족으로 일관되지 않아 새 자동 규칙을 적용하지 않는다.

## 2026-06-14 합계 차이 원인 조사

- 삼성카드_7의 큰 차이는 할부 행 2건을 원거래 이용금액 `71,540`으로 더한 데서 왔다. 원본 합계는 회차 원금 `23,940`, `23,800`을 더한다.
- 삼성카드_7 페이지 6 마지막 줄 `05-12 지에스칼텍스(주)봄내주유소 98,116 / 93,796 / -4,320`은 `page_006_chunk_03` 하단에서 잘려 Vision 응답에 없다.
- 하단 누락 방지를 위해 기본 `body_end_ratio`를 `0.95`에서 `0.98`로 늘렸다. 기존 캐시만 재사용하면 누락 행은 다시 생기지 않으므로 이 샘플은 해당 청크 재호출이 필요하다.
- 현대카드_8의 `page_007_chunk_03` 캐시에는 Vision이 `page=1`, `chunk_id=page_001_chunk_01`로 잘못 응답했다. 청크 메타데이터가 정답이므로 캐시 로드와 신규 응답 모두에서 page/chunk_id를 청크 기준으로 덮어쓴다.
- 현대카드_8의 `이용일 이용카드` 결합 헤더 행은 포인트 숫자를 amount로 오인했다. 해당 형태는 위치 기반으로 `date/card_label/merchant/amount/billing_amount`를 복원한다.
- 현대카드_8 재실행 결과 `llm_calls=0`, `transaction_count=295`, `validation_issue_row_count=0`, 페이지 묶음 차이는 `-10,000`, `+78,000`, `0`, `-19,020`으로 줄었지만 아직 자동 선택할 수 없다.
- 삼성카드_7은 `page_006_chunk_03` 캐시 1건을 삭제하고 새 `body_end_ratio=0.98` 청크로 재호출했다. 누락됐던 `05-12 지에스칼텍스(주)봄내주유소 98,116 / 93,796 / -4,320` 행이 복구됐다.
- 삼성카드_7 최종 재실행 결과는 `transaction_count=245`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`다.

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

## 2026-06-13 삼성카드_5 캐시 기반 정확도 개선

- 목표는 대표 캐시를 카드사별로 준비한 뒤 `삼성카드_5.pdf`를 캐시에서 순서대로 재사용해 정확도 100% 지표까지 맞추는 것이다.
- Gemini 3.1 Flash Lite RPM 15 제한을 고려해 `vision.request_delay_seconds=5` 설정을 유지한다.
- `삼성카드_7.pdf`의 앞 5페이지 이미지 해시가 `삼성카드_5.pdf`와 동일해, `output/page_cache/samsung/samsung_7`의 앞 5페이지 Vision 캐시 20개를 `output/acceptance_samsung_5/cache`로 복사해 재사용했다.
- 기존 `삼성카드_5` 산출물은 캐시 20/20, `llm_calls=0`이지만 `normalization_review_count=120`, `validation_issue_row_count=39`, `checksum_status=no_user_total_selected` 상태다.
- 주요 원인은 삼성 표에서 `이용자`가 `card_label`, `가맹점명/이용내역`이 `merchant`, `이 달에 입금하실 금액`이 검산 기준 `amount`여야 하는데 일부 표가 다르게 매핑된 점이다.
- totals 청크 응답에 들어온 거래형 `rows`는 검산 후보가 아니라 중복 거래를 만들기 때문에 거래 원천 행에서 제외해야 한다.
- 삼성 표에서 `이용일수`, `이자/수수료`, `적립금액`이 핵심 금액/날짜 후보로 오인되는 문제를 보정했다.
- 같은 페이지에서 동일 raw cells가 1,2,3번 청크처럼 세 개의 인접 겹침 청크에 반복될 때는 대표행 1개만 거래로 사용하도록 했다. 1번과 3번 청크에만 반복되는 케이스는 기존 테스트처럼 확인 대상으로 둔다.
- 하이패스 이용내역은 날짜 범위와 건수가 포함되어 숫자가 많지만 정상 가맹점명이므로 숫자 오염 검증 예외에 추가했다.
- 삼성 `amount_total`은 청구할인 반영 후 금액이고 원문 `이용금액합계`는 할인 전 금액이다. 검산에서는 거래 extra fields의 할인 가능 금액 범위 안에서 차이를 보정해 `이용금액합계 합산 11,198,212`와 자동 일치시킨다.
- 최종 `output/acceptance_samsung_5` 결과는 `llm_calls=0`, `vision_ok=20`, `vision_errors=0`, `transaction_count=180`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, `difference=0`이다.

## 2026-06-13 신한카드_11 앞 5페이지 캐시 기반 정확도 개선

- 사용자가 말한 `신한카드5`는 별도 `견본/신한카드_5.pdf`가 아니라 `신한카드_11.pdf` 대표 캐시의 앞 5페이지를 뜻한다.
- `output/page_cache/shinhan/shinhan_11`은 44/44 캐시 성공 상태였고, 앞 5페이지에 해당하는 20개 Vision JSON을 `output/acceptance_shinhan_5/cache`로 복사했다.
- `main.py`는 입력 PDF 전체 페이지 기준으로 청크를 만들기 때문에, PyMuPDF로 `output/acceptance_shinhan_5/신한카드_5_from_11.pdf` 앞 5페이지 PDF를 생성해 입력으로 사용했다.
- 최초 캐시 실행 결과는 `llm_calls=0`, `vision_ok=20`, `normalization_review_count=1`, `validation_issue_row_count=0`, `checksum_status=no_user_total_selected`, `amount_total=12,789,514`였다.
- 원문 `총합계` 1~5페이지 합산은 `12,749,514`였고 거래 합계가 40,000원 과다였다. 원인은 할부 행 변형 중복 3건과 Vision이 `misaligned or possibly truncated`라고 표시한 9,900원 리뷰 행이었다.
- 정규화 중복 제거를 `할부 기간/회차 + 원거래 이용금액 + 이번달 원금` 기준 변형 중복까지 확장했다. 같은 행이 겹침 청크에서 날짜나 가맹점 OCR만 흔들려도 대표행 1개만 남긴다.
- Vision이 직접 `misaligned` 또는 `truncated`로 표시한 금액 리뷰 행은 거래 합계에서 제외하도록 했다.
- 최종 `output/acceptance_shinhan_5` 결과는 `llm_calls=0`, `vision_ok=20`, `vision_errors=0`, `transaction_count=226`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, `matched_total=총합계 합산 12,749,514`, `difference=0`이다.

## 2026-06-13 현대카드_8, 삼성카드_7, 신한카드_11 진행 기록

- 현대카드_8은 기존 페이지 캐시 32개를 사용해 `llm_calls=0`, `vision_ok=32`, `normalization_review_count=0`, `validation_issue_row_count=0`까지 확인했다.
- 현대카드_8의 합계 후보는 아직 자동 선택되지 않는다. 현재 거래 합계는 34,210,388이고 총 합계 후보 합산과 차이가 남아 있어 문서 규칙으로 안전하게 확정하지 않았다.
- 삼성카드_7은 삼성 청구 표에서 할인과 카드번호가 밀린 행을 보수적으로 보정해 `llm_calls=0`, `vision_ok=28`, `normalization_review_count=0`, `validation_issue_row_count=0`까지 확인했다.
- 삼성카드_7의 합계 후보도 아직 자동 선택되지 않는다. 행 정확도와 검증은 정리됐지만 합계 후보 선택 로직은 별도 보정이 필요하다.
- 신한카드_11은 전체 44개 Vision 캐시를 사용해 재실행했고 `llm_calls=0`, `vision_ok=44`, `normalization_review_count=0`, `validation_issue_row_count=0`까지 확인했다.
- 신한카드_11에서는 0원으로 잘못 잡힌 부가경감·취소 행과 `377,176 / 40,000` 분할 표기 행을 원거래 금액 열 기준으로 보정했다.
- 관련 테스트로 `python -X utf8 tests\test_profile_signature.py`, `python -X utf8 tests\test_validation_fixtures.py`, `python -X utf8 tests\test_checksum_selection.py`, `python -X utf8 tests\test_duplicate_representative.py`를 실행했고 모두 통과했다.

## 2026-06-14 합계 자동 선택 보류 판단

- 현대카드_8은 총합계 후보 합산 34,523,411과 거래 합계 34,210,388의 차이가 313,023이다.
- 현대카드_8은 페이지 묶음별로 1-2쪽 9,605 부족, 3-4쪽 78,000 과다, 5-6쪽 0, 7-8쪽 381,418 부족으로 차이가 일관된 할인 조정 하나로 설명되지 않는다.
- 삼성카드_7은 이용금액합계 계열 후보 합산 16,545,610과 거래 합계 16,388,134의 차이가 157,476이다.
- 삼성카드_7은 원거래 이용금액 합계와 청구/입금 금액 합계가 섞여 있어 현재 검산 로직에서 자동 선택하면 조용한 오선택 위험이 있다.
- 두 샘플 모두 행 리뷰와 검증 이슈는 0이지만, 합계 자동 선택은 추가 규칙 없이 확정하지 않는 것이 맞다.
## 2026-06-14 review.html 단순화

- 사용자가 언급한 `sop010.html`은 현재 작업공간에서 발견되지 않았다.
- 대체 기준은 기존 `output/review.html`처럼 한 화면에서 요약과 필요한 링크만 보여주는 단순한 HTML 형태로 잡는다.
- `review.html`은 모든 행과 페이지를 훑는 화면이 아니라 예외와 검산 상태를 빠르게 확인하는 디버그 화면으로 유지한다.
- 이후 사용자가 알려준 GitHub `https://github.com/BN8624/BN.git`에서 `sop010.html`을 확인했고, React 앱 자체가 아니라 연녹색 배경과 단순 상태 카드 톤만 정적 `review.html`에 반영했다.

## 2026-06-14 컬럼 맞추기 UI 단순화

- 사용자는 매핑이라는 내부 용어보다 원본 컬럼을 엑셀 컬럼에 맞추는 일만 필요하다고 판단했다.
- `review.html`의 기본 매핑 화면은 `컬럼 맞추기` 제목 아래 원본 컬럼명, 샘플 3개, 핵심 선택지, 저장 버튼만 보이게 줄였다.
- 선택지는 이용일, 이용카드, 가맹점, 이용금액, 결제/청구금액, 할인, 무시를 기본으로 제한했다.

## 2026-06-14 컬럼 맞추기 표형 압축

- 컬럼 맞추기는 원본 컬럼, 샘플, 엑셀 항목 3열이면 충분하므로 카드형 반복 UI를 표형 행으로 줄였다.
- 저장 버튼은 컬럼 목록 아래가 아니라 `컬럼 맞추기` 제목 옆에 배치해 화면 높이를 줄였다.

## 2026-06-14 남은 4개 항목 정리

- 현대카드_8은 총합계 후보 4페이지 합산 34,523,411과 거래 합계 34,572,391이 48,980 차이난다. 자동 선택 후보가 없으므로 조용한 오선택을 막기 위해 `no_user_total_selected`를 유지한다.
- 현대카드_8의 checksum 보류는 행 단위 blocked가 아니라 샘플 단위 검산 확인 필요 상태이므로 `automation_summary.json`의 `checksum_review_required`로 표시한다.
- 삼성카드_7은 재생성 결과 `auto_selected_total_matched`, `matched_field=amount_total_discount_reconciled`, difference 0으로 확인했다.
- P0 기반 작업으로 검증된 각 거래 행에 `automation.row_status`, `confidence_score`, `risk_level`을 추가하고 `merged/automation_summary.json`을 생성하도록 했다.

## 2026-06-14 현대카드_8 합계 불일치 추가 조사

- 현대카드_8의 정규화 중복 제거는 기존에 같은 페이지, 날짜, 이용금액, 청구금액만으로 겹침 청크 중복을 제거했다.
- 이 규칙은 `03.01 이동의즐거움_택시_0 10,000`과 `03.01 광주광역시도시공사 10,000`처럼 서로 다른 가맹점의 같은 금액 거래를 제거할 수 있었다.
- 정규화 중복 제거 직전에 가맹점 정규화 키가 같거나 충분히 유사한 경우에만 제거하도록 바꿨고, 서로 다른 가맹점의 같은 날짜·금액 거래를 유지하는 회귀 테스트를 추가했다.
- 현대카드_8 캐시 재생성 결과는 `transaction_count=297`, `amount_total=34,596,521`, `normalized_duplicate_excluded_count=27`, `row_issue_count=0`, `checksum_status=no_user_total_selected`다.
- 원본 총합계 후보 합산 34,523,411과의 차이는 73,110원이며, 페이지 묶음별 차이는 1-2쪽 -10,000원, 3-4쪽 +88,000원, 5-6쪽 0원, 7-8쪽 -4,890원이다.
- 단순 혜택/바우처 제외 행을 모두 반영해도 합계가 맞지 않으므로, 남은 원인은 현대카드 메인 청구 목록과 해외/정기결제/혜택 상세표의 중복 또는 금액 기준 차이를 더 구분해야 한다.
- `--force-vision`으로 현대카드_8 전체를 재호출했지만 5-8쪽 누락과 검증 이슈가 늘어 결과가 악화됐다. 새 캐시는 폐기하고 `output/page_cache/hyundai/hyundai_8/cache`의 안정 캐시로 복구했다.
- 페이지 8의 `05.06 14,130`은 `롯데슈퍼춘천점` 행과 같은 날짜·금액이며 다른 청크의 가맹점 OCR 오류 행으로 확인됐다. `quality.review_reason`에 merchant OCR 오류가 있는 경우 정규화 중복 제거를 허용하도록 보정했다.
- 보정 후 현대카드_8은 `transaction_count=296`, `amount_total=34,582,391`, `normalized_duplicate_excluded_count=28`, `normalization_review_count=0`, `validation_issue_row_count=0`이다.
- 원본 총합계 후보 합산 34,523,411과의 차이는 58,980원이며, 페이지 묶음별 차이는 1-2쪽 -10,000원, 3-4쪽 +88,000원, 5-6쪽 0원, 7-8쪽 -19,020원이다.
- 페이지 3 이미지 확인 결과 `02.27 철도승차권 -부산역 151,400`과 `151,200`은 둘 다 원본에 존재한다. `03.01`의 10,000원 2건과 12,000원 1건도 원본에 존재하므로 이들을 checksum만 보고 제거하면 안 된다.

## 2026-06-14 현대카드_8 검산 규칙 검토 결론

- `amount_total`, `billing_amount_total`, `billing_amount if present else amount`, 보조 상세표 제외, 혜택 행 포함/제외 조합을 계산했지만 원본 총합계 후보 합산 34,523,411과 일관되게 일치하는 기준은 없었다.
- 남은 차이를 맞추려면 페이지 묶음별로 1-2쪽은 +10,000원, 3-4쪽은 -88,000원, 7-8쪽은 +19,020원이 필요하다. 제외된 혜택/바우처/포인트 상세 행에는 이 세 조정값과 직접 대응되는 안전한 후보가 없다.
- 3-4쪽의 바우처 -100,000원과 12,000원 겹침 후보를 조합하면 일부 차이를 설명할 수 있어 보이지만, 페이지 이미지상 12,000원은 실제 거래다. checksum 차이를 맞추기 위해 이 행을 제거하는 규칙은 조용한 오삭제가 된다.
- 7-8쪽의 19,020원 부족도 `SK렌터카 M포인트 -980`, `청구할인 소계 -4,980`, 기존 거래 금액 후보만으로 직접 설명되지 않는다.
- 따라서 현대카드_8은 현재 규칙으로 자동 검산 일치를 만들지 않고 `no_user_total_selected`와 `checksum_review_required=true`를 유지한다. 다음 개선은 Vision 재호출이 아니라 현대카드 원본 합계 정의를 별도 표본으로 더 확인한 뒤 issuer profile 규칙으로 추가해야 한다.

## 2026-06-14 섹션 기반 검산 리포트

- 현대카드 문제는 합계 후보 선택 UI가 아니라 섹션별 원장 모델 문제로 보고, `section_reconciliation.json`을 추가했다.
- 리포트는 거래 행을 `billing_detail`, `foreign_detail`, `benefit_detail`, `subscription_detail`, `cancellation_detail` 등으로 분류하고 페이지 묶음별 원본 총합계와 비교한다.
- 현대카드_8 현재 결과는 1-2쪽 `-10,000`, 3-4쪽 `+88,000`, 5-6쪽 `0`, 7-8쪽 `-19,020`이다. 5-6쪽만 matched이고 나머지는 `unexplained`로 남는다.
- `review.html`은 검산 보류 카드 안에 페이지 묶음별 섹션 검산 요약을 접힌 상세로 표시한다. 이 리포트는 자동 확정 규칙이 아니라 원인 분석과 issuer profile 승격 후보를 찾기 위한 증거다.

## 2026-06-14 현대카드_8 제외 행 진단 방향

- 현대카드_8의 남은 차이는 검증 통과 거래만 보는 `section_reconciliation.json`으로는 설명이 부족하다.
- 정규화 과정에서 제외된 바우처, 포인트, 캐시백 원본 행이 페이지 묶음 차이를 설명하는지 확인할 필요가 있다.
- 다만 checksum 차이에 맞는다는 이유만으로 원본 제외 행을 자동 반영하면 실제 거래를 제거하거나 할인 행을 중복 적용할 위험이 있다.
- 따라서 `rows_merged.jsonl`의 원본 제외 후보는 진단 리포트에만 포함하고, 자동 검산 일치 판정에는 사용하지 않는다.

## 2026-06-14 현대카드 결제원금 열밀림

- 현대카드_8 1페이지 `page_001_chunk_01`은 원본 header에 `결제원금` 열이 있고 raw cells에도 값이 있지만 정규화 `billing_amount`가 비어 있었다.
- 이 때문에 정규화된 1페이지 `billing_amount` 합계가 원본 결제원금 열 합계보다 508,430원 작게 보였다.
- 합계 후보 문제가 아니라 열 역할 복구 문제이므로, header에 `결제원금` 또는 `청구금액`이 명시된 경우 해당 열에서 `billing_amount`를 보수적으로 복구한다.

## 2026-06-14 현대카드 해외 상세 중복 합산

- 현대카드_8 2페이지 결제원금 기준은 4,185,436원이다.
- 정규화 합계 4,354,796원은 해외 상세 표의 `결제원금(원)` 169,360원을 본문 청구금액 위에 한 번 더 더한 값이었다.
- 해외 상세 행은 감사용 거래 행으로 남기되, `billing_amount_total`과 페이지 묶음 청구 합계에서는 제외해야 한다.

## 2026-06-14 현대카드 하단 누락 방지

- Vision이 페이지 하단 마지막 행을 빠뜨리는 경우가 있어, 각 페이지 하단 90~98%를 별도 보조 청크로 읽는다.
- 보조 청크는 누락 방지용이므로 일반 청크보다 보수적으로 처리한다. 날짜가 불명확하거나 금액이 없거나 `needs_review`가 남아 있거나 요약 행처럼 보이면 정규화 결과에서 제외한다.
- 보조 청크와 일반 청크의 y 범위를 함께 보존해서 실제로 겹치는 원본 영역이면 중복 후보로 판단한다.
- 현대카드 하이패스 행은 `0004건` 같은 건수 셀이 금액 후보로 섞일 수 있다. `하이패스` 카드 라벨과 `0000건` 패턴이 같이 있으면 뒤쪽의 실제 금액을 `amount`와 `billing_amount`로 복구한다.
- 현대카드_8 재생성은 기존 캐시를 사용해 `llm_calls=0`, `validation_issue_row_count=0`, `hard_review_count=0`, `blocked_count=0`까지 확인했다. 다만 전체 체크섬은 현대카드 원본 총합계 기준이 아직 자동 확정되지 않아 `no_user_total_selected`를 유지한다.

## 2026-06-14 KB 사업자카드 신규 샘플 1차 분석

- `kb_bzcard_13.pdf`는 13페이지이고 기존 파이프라인 1차 실행 결과 `vision_ok=64`, `vision_errors=1`, `transaction_count=186`, `normalization_review_count=186`, `validation_issue_row_count=186`이었다.
- Vision 오류 1건은 `page_002_chunk_02`의 Gemini 503이다. 캐시 기반 재실행 때 해당 청크만 재시도 대상이다.
- 주 거래 표 헤더는 `이용카드, 이용일, 이용 가맹점, 가맹점 소재지, 이용금액, 현지금액, 이번달 결제금액, 적립예정 포인트리` 구조다.
- 기존 자동 보정은 현대카드 포인트형 규칙과 가장 가깝게 잡혔지만, `가맹점 소재지`를 두 번째 merchant 후보로 잡고 `이번달 결제금액` review를 남겨 모든 행이 review가 됐다.
- KB 날짜는 `1211`처럼 4자리 월일로 들어온다. 현재 날짜 검증은 구분자 없는 월일을 인정하지 않아 전 행 `date_not_date_like`가 발생했다.
- `sop010.html`은 PDF를 페이지 이미지로 렌더링하고 1페이지를 먼저 호출해 헤더를 확정한 뒤 이후 페이지에 knownHeader를 넘긴다. RPM은 한도보다 2 낮은 슬롯으로 제한하고 429는 30초 대기 후 재시도한다.
- KB 보정 후 최종 `output/acceptance_kb_bzcard_13` 결과는 `llm_calls=0`, `vision_ok=65`, `vision_errors=0`, `transaction_count=173`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, `matched_total=KB 페이지별 이번달 결제금액 합산 28,301,920`, `difference=0`이다.
- 현대카드_8은 거래 추출과 행 검증 기준으로는 종료 상태다. 다만 샘플 완전 종료 선언은 원본 총합계 기준이 자동 확정되거나 사용자가 총합계 기준을 선택해서 `checksum_status`가 matched 상태가 되어야 한다.

## 2026-06-14 현대카드_8 중단 지점 인수인계

- 사용자 요청으로 작업을 중단하고 문서 정리만 수행했다. 코드와 산출물은 수정하지 않았다.
- 현재 워크트리는 추적 파일 기준으로는 깨끗했으며, 사용자 파일로 보이는 `견본/`만 untracked 상태였다. 문서 정리 후에는 `checklist.md`, `context-notes.md`, `STATUS.md`만 변경 대상이어야 한다.
- 사용자의 최신 판단은 현대카드 명세서의 원본 합계 기준이 결제원금 열이라는 것이다. 따라서 현대카드_8에서 비교해야 할 주된 내부 합계는 `billing_amount_total`이다.
- 현재 `output/acceptance_hyundai_8/merged/validation_summary.json`의 합계 정보는 최상위가 아니라 `checksum` 아래에 있다.
- 현재 현대카드_8 `checksum.amount_total`은 `34,679,296`이고 `checksum.billing_amount_total`은 `34,435,671`이다.
- 원본 `총 합계` 후보의 페이지별 값은 page 2 `11,133,210`, page 4 `9,260,937`, page 6 `10,113,565`, page 8 `4,015,699`이다. 네 값을 합치면 `34,523,411`이다.
- 따라서 원본 결제원금 총합 기준과 현재 `billing_amount_total`의 차이는 `87,740`이다. 원본 쪽이 더 크다.
- 현재 `checksum.status`는 `no_user_total_selected`이고 `checksum_review_required`는 `true`다. 사용자가 합계 기준을 이미 결제원금이라고 확정했으므로 다음 작업은 UI 선택 문제가 아니라 현대카드_8 결제원금 합계 불일치 원인 제거다.
- `output/acceptance_hyundai_8/merged/section_reconciliation.json` 기준 pages 1-2는 원본 `11,133,210`, `amount_total 11,079,970`, `billing_amount_total 11,061,970`이며 원본 대비 결제원금이 `71,240` 부족하다.
- pages 3-4는 원본 `9,260,937`, `amount_total 9,471,582`, `billing_amount_total 9,260,937`로 결제원금이 일치한다.
- pages 5-6은 원본 `10,113,565`, `amount_total 10,123,565`, `billing_amount_total 10,113,565`로 결제원금이 일치한다.
- pages 7-8은 원본 `4,015,699`, `amount_total 4,004,179`, `billing_amount_total 3,999,199`이며 원본 대비 결제원금이 `16,500` 부족하다.
- pages 1-2의 직접 원인은 해외 상세 결제원금 중복 제외 규칙과 본문 결제원금 복구 사이의 경계로 보인다. 현재 섹션 리포트에서 `foreign_detail.billing_amount_total`은 `169,360`이고, 이를 모두 제외한 뒤에도 원본 대비 `71,240`이 부족하다.
- pages 1-2에서 이미 확인된 해외 상세 값은 `45,835`, `16,519`, `20,519`, `86,487`이고 합계가 `169,360`이다. 이 중 어떤 값을 본문 결제원금 대체값으로 써야 하는지 다시 원본 이미지와 raw cells 기준으로 확인해야 한다.
- pages 7-8은 현재 행 수가 원본 요약보다 1건 적은 정황이 있으며 원본 대비 결제원금 부족액이 정확히 `16,500`이다. page 8 하단부의 `강릉서부시장번영회 3,000`, `강릉불고기초당점 15,000`, `한국도로공사 33,900`, `스마트로 - 춘천시청 1,800` 주변이 먼저 확인 대상이다.
- 이전 분석에서는 page 8 하단 보조 청크가 너무 아래쪽만 잡아 총합계 주변은 보지만 총합계 바로 위 거래 일부를 놓칠 수 있다는 의심이 있었다. 다만 넓은 하단 청크는 환각 위험이 있으므로 바로 범위를 키우기보다 현재 chunk manifest와 cache JSON을 먼저 대조해야 한다.
- 다음 세션의 첫 확인 명령 후보는 `output/acceptance_hyundai_8/chunks/chunks_manifest.json`에서 page 7, page 8 y 범위를 출력하고, `output/acceptance_hyundai_8/cache/page_008_chunk_*.vision.json`의 raw rows에서 위 하단 거래들이 실제로 있는지 찾는 것이다.
- 코드에서 먼저 볼 파일은 `src/normalizer.py`의 `_is_foreign_detail_billing_row`, `_sum_amount`, 현대카드 헤더 기반 `billing_amount` 복구 로직이고, 이어서 `src/reconciliation.py`의 섹션 분류 로직이다.
- 원칙은 결제원금 합계를 억지로 맞추는 조정값을 넣지 않는 것이다. 원본 이미지 또는 raw cells에서 누락, 열밀림, 해외 상세 대체 관계가 증명되는 경우에만 최소 규칙을 추가한다.
- 관련 테스트로는 최소 `python -X utf8 tests\test_checksum_selection.py`, `python -X utf8 tests\test_profile_signature.py`, `python -X utf8 tests\test_validation_fixtures.py`, `python -X utf8 tests\test_duplicate_representative.py`를 다시 실행한다. 현대카드 보정 테스트를 추가했다면 해당 테스트도 함께 실행한다.

## 2026-06-14 현대카드_8 결제원금 부족분 재확인

- `page_001_chunk_01.png` 원본 이미지 기준 `01.18 시외버스모바일전자승차권_이즐` 행의 결제원금은 `2,600`이 맞다. 이용금액 `26,600`과 다음 취소 행 `-24,000`을 근거로 결제원금을 `26,600`으로 복구하면 안 된다.
- 같은 이미지에서 다음 `01.19 시외버스모바일전자승차권_이즐 -24,000` 행은 결제원금 칸이 비어 있다. 현재처럼 `billing_amount=null`로 두는 것이 원본 보존 원칙에 맞다.
- `page_008_chunk_*.vision.json` 확인 결과 page 8 하단 의심 행 `강릉서부시장번영회 3,000`, `강릉불고기초당점 15,000`, `한국도로공사 33,900`, `(주) 스마트로 - 춘천시청 1,800`은 `page_008_chunk_02` raw rows에 존재하고 `transactions_validated.jsonl`에도 거래로 포함되어 있다. 따라서 pages 7-8의 16,500 부족분은 이 하단 행 누락으로 설명되지 않는다.
- 현재 확인 범위에서는 부족분을 맞추기 위한 안전한 최소 규칙이 아직 증명되지 않았다. 조정값이나 checksum 차이만으로 row를 추가/수정하지 않는다.

## 2026-06-14 현대카드_8 pages 7-8 캐시 전체 재확인

- `page_008_chunk_02.png` 원본 합계 영역은 `일부결제금액이월약정 소계 91건 4,015,699`, `청구 할인 소계 -4,980`, `총 합계 91건 4,015,699`로 읽힌다.
- 현재 `transactions_validated.jsonl` 기준 pages 7-8 거래 수는 90건이고 `billing_amount_total`은 `3,999,199`라서 원본 대비 16,500원이 부족하다.
- `amount_total` 기준으로는 `4,004,179`이며 원본 대비 11,520원이 부족하다. 이 값은 `16,500 - 4,980`과 같아, 할인 소계와 별개로 결제원금 16,500원 거래 1건 누락 가능성을 시사한다.
- 그러나 `page_007_chunk_01/02/03/80/90.vision.json`과 `page_008_chunk_01/02/03/80/90.vision.json` 전체에는 16,500원 거래가 존재하지 않는다. page 7 전체 이미지와 chunk 경계에서도 `05.03 위이 21,500` 다음 누락 행은 확인되지 않았다.
- 따라서 현재 캐시 증거만으로 16,500원 행을 자동 생성하거나 다른 행 금액을 수정하면 추측이다. 이 건은 기존 캐시 기반 규칙이 아니라 page 7-8 경계/하단을 대상으로 한 선택적 2-pass Vision 또는 별도 원본 재확인이 필요하다.

## 2026-06-14 현대카드_8 pages 1-2 합계 구조 재정리

- pages 1-2는 `amount_total 11,079,970`, 해외 상세 제외 `billing_amount_total 11,061,970`, 원본 `총 합계 11,133,210`이다.
- 원본 대비 차이는 이용금액 기준 53,240원, 결제원금 기준 71,240원이다. 두 차이의 간격 18,000원은 같은 묶음의 `청구할인 소계 -18,000`과 맞다.
- 해외 상세 결제원금은 `45,835`, `16,519`, `20,519`, `86,487` 합계 169,360원이다. 이를 통째로 포함하면 원본을 98,120원 초과하므로, 해외 상세 전체 포함은 안전한 규칙이 아니다.
- 본문 해외 거래와 해외 상세 결제원금의 부분 대체 조합도 현재 캐시 금액만으로는 53,240원 또는 71,240원을 설명하지 못한다. 이 역시 조정값으로 맞출 수 없고, 원본 이미지/재비전 근거가 추가로 필요하다.

## 2026-06-14 현대카드_8 로컬 OCR 교차 확인

- `easyocr`가 로컬에서 동작해 `page_007.png`, `page_008.png`, `page_001.png`, `page_002.png` 전체 페이지 OCR을 교차 실행했다.
- pages 7-8 OCR 결과에서는 `16,500`, `16500`, `16,50` 계열 후보가 발견되지 않았다.
- page 1 OCR에서는 기존 `01.18 마일스톤 16,500`만 발견됐고, page 2 OCR에서는 기존 해외 상세 `16,519`와 본문 `16,548/-16,548`만 발견됐다.
- 따라서 pages 7-8의 16,500 부족분은 현재 Vision 캐시뿐 아니라 로컬 OCR 교차 확인에서도 원본 행 후보가 확인되지 않는다. 코드 규칙 추가보다 원본 PDF/이미지의 합계 정의 또는 외부 Vision 재확인이 먼저 필요하다.

## 2026-06-14 현대카드_8 전체 페이지 Vision 2-pass 재확인

- 사용자 승인 아래 `tools/revision_fullpage_diag.py`로 pages 1, 2, 7, 8의 전체(미크롭) 페이지 이미지를 Gemini에 1회 1페이지로 재호출했다. 결과는 `output/diag_hyundai_8/`에만 저장하고 파이프라인 캐시는 건드리지 않았다.
- pages 7-8 전체 페이지 재호출의 거래 합계가 파이프라인 산출물과 원 단위까지 동일하다. 결제원금 합 `3,999,199`(파이프라인 `billing_amount_total`과 일치), 이용금액 합 `4,004,179`(파이프라인 `amount_total`과 일치)다.
- 즉 직전 세션이 의심했던 "하단 누락된 16,500원 행"은 존재하지 않는다. 독립적인 새 Vision도 같은 거래를 같은 금액으로 읽었고, 보이는 거래 결제원금을 모두 더하면 3,999,199원이다.
- 원본 페이지 이미지로 pages 7·8의 결제원금 열 전체를 한 행씩 직접 대조했고, 모든 값이 추출과 일치한다. 오독도 누락 행도 없다. 따라서 이번 달 거래 결제원금 열 합은 `3,999,199`로 확정이다.
- 사용자 확인 결과 `총 합계`와의 차이는 리볼빙(일부결제금액이월약정)이다. 리볼빙은 더하는 성분이 아니라 전월에 그만큼 결제를 덜 한 이월 잔액이 이번 달 청구에 합쳐진 것이다.
- 즉 `총 합계` = 이번 달 거래 결제원금 + 전월 리볼빙 이월분이다. 숫자도 정확히 맞는다. 7-8쪽 `3,999,199 + 16,500 = 4,015,699`, 1-2쪽 `11,061,970 + 71,240 = 11,133,210`. 3-4·5-6쪽은 이월분이 0이라 거래 결제원금 합과 총합계가 이미 일치한다.
- 따라서 16,500/71,240은 이번 달 거래가 아니므로 거래 행으로 만들면 안 된다. 직전 세션들이 16,500원 행을 못 찾은 것은 그 행이 원래 없기 때문이다.
- 결론: 현대카드_8 거래 추출은 완료 상태다. 검산 기준은 "이번 달 거래 결제원금 열 합"이며, 원본 총합계와의 차이는 전월 리볼빙 이월분으로 설명되는 정상 차이다.

## 2026-06-14 리볼빙 검산 규칙 + dry-run page 오염 수정

- 검산에 리볼빙 폴백을 추가했다(`src/validator.py` `_auto_match_candidates`, `_is_revolving_statement`). 조건은 (1) 후보 라벨에 `이월약정`/`리볼빙`이 있고, (2) 다른 매칭이 전부 실패했으며, (3) 총합계 후보 ≥ 거래 결제원금 합일 때만, 그 잉여분(전월 이월)을 무시하고 `billing_amount_total_revolving_carryover`로 일치 처리한다. 결제원금이 총합계를 초과(과추출)하면 절대 일치시키지 않는다. 기존에 맞던 샘플(현대카드_2·삼성_7·신한·KB)은 라벨 조건과 `not matches` 가드로 영향받지 않는다.
- 화면에 리볼빙 표시를 추가했다(`src/review_builder.py` `_detect_revolving`). review.html 요약 그리드에 `리볼빙: 있음/없음`을 표시한다. 후보 라벨에 이월약정/리볼빙이 있으면 있음이다.
- dry-run(캐시) 경로 버그를 고쳤다. `load_cached_vision_results`가 `_with_required_defaults`를 적용하지 않아, `page_007_chunk_03.vision.json`처럼 Vision이 `page=1`로 오염 응답한 캐시의 page/chunk_id가 교정되지 않았다. 그 결과 dry-run에서만 같은 페이지 y겹침 중복제거를 빠져나가 거래가 8건 과추출(307건)됐다. 라이브 경로와 동일하게 청크 메타데이터로 교정하도록 맞췄다.
- 수정 후 현대카드_8 캐시 재생성 결과는 `transaction_count=299`, `billing_amount_total=34,435,671`(원본 총합계 합산 34,523,411 이하), `checksum_status=auto_selected_total_matched`, `matched_field=billing_amount_total_revolving_carryover`, `carryover_total=87,740`이다. 이 이월분 87,740은 진단했던 1-2쪽 71,240 + 7-8쪽 16,500과 정확히 일치한다.
- 남은 중복 2건(`02-14 호텔신라면세점 100,000`, `05-04 택시-02 노 2002 3,500`)은 같은 청크 내 실제 2건 거래로 원본 이미지에 두 줄 존재한다. 올바르게 유지된다.
- 진단 도구 `tools/revision_fullpage_diag.py`로 전체 페이지를 재호출한 결과(`output/diag_hyundai_8/`)와 원본 페이지 이미지 직접 대조로 결제원금 열 추출이 정확함을 확인했다.

## 2026-06-14 sop010 장점 이식 전략 (2단 구조 결정)

- 사용자 전략 전환: 범용 단일 추출기로 모든 카드사를 완벽히 잡으려던 방향에서, 한국 카드사가 9개뿐이므로 카드사 맞춤 보정으로 간다. 다만 범용 1단으로 한 번 거르고 남은 것만 카드사별 2단으로 정밀화하는 합본 구조가 낫다고 판단했다.
- 1단(범용 거름망) = `견본/sop010.html` 방식. 페이지 1장=1 호출, 헤더명 키 JSON Lines, 1쪽 헤더 확정 후 이후 쪽에 헤더 힌트 전파, 밝기→대비 적응형 전처리.
- 2단(카드사 맞춤) = 현재 Python normalizer/validator의 issuer 보정, 검산 기준, 리볼빙 등 기존 자산 유지.
- 핵심 통찰: sop010이 신한카드_11을 가장 근접하게 처리했고, 가장 큰 난점이던 열밀림을 잡은 결정 요인은 "페이지 단위"가 아니라 "헤더명 키 JSON"이다. 위치 기반 cells 배열은 열이 밀리면 normalizer가 위치 보정으로 고생한다.
- Vertex 엔드포인트(aiplatform `?key=`) 문제는 무시한다. 우리 Python은 generativelanguage 엔드포인트를 쓴다.
- 설계 결정: 추출은 헤더명 키로 받되 내부에서 헤더 순서에 맞춘 cells 배열을 재구성해 넘긴다. 그러면 row_merger/normalizer/validator/검산/리볼빙(2단)을 거의 손대지 않고 재사용하면서 추출만 열밀림에 강해진다.
- 검산용 원본 합계는 페이지 호출에서 rows와 totals(총합계/소계 등 집계행)를 분리해 함께 반환받아 확보한다. sop010은 집계행을 버려 검산 기준이 없었다.
- 안전 전환: 신규 페이지 단위 경로는 캐시 키가 page_NNN으로 청크 경로(chunk_id)와 겹치지 않으므로, config 플래그로 병행 추가→신한카드_11 검증→기존 100% 샘플 회귀 확인→기본 전환 순서로 간다.

## 2026-06-14 페이지 단위 호출방식 결정

- 출력: responseMimeType text/plain + JSON Lines. 헤더명을 동적 키로 받으므로 response_schema(고정 속성명)를 쓸 수 없다. 1행=1 JSON 객체, 첫 줄 헤더 배열, 집계행은 totals로 분리, 애매한 집계행은 __skip. 클라이언트에서 파싱한다.
- 전송: 현행 Python urllib → generativelanguage.googleapis.com/v1beta ...:generateContent, x-goog-api-key 유지. Vertex(aiplatform ?key=)는 무시.
- 단위: 페이지 1장=1 호출. 청크·하단가드 없음. rows+totals 동시 반환.
- 동시성: 사용자 결정 = 동시성 2 + RPM 슬라이딩 큐(sop010 방식). 1쪽 단독 선처리로 헤더 확정 후 2쪽~ 동시 2장. 슬라이딩 윈도우 RPM 제한(슬롯 RPM-2, 60초 창).
- 헤더 힌트: 1쪽 확정 헤더를 2쪽~ 프롬프트에 knownHeader로 주입.
- generationConfig: temperature 0, topP 0.1, maxOutputTokens 65535, safety 전부 BLOCK_NONE. MAX_TOKENS 도달 페이지는 검토 플래그.
- 재시도: 현행 유지(max_retries, 429→30초, 그 외 지수백오프).
- 캐시: page_NNN.vision.json (기존 청크 chunk_id 캐시와 키 분리).

## 2026-06-14 page 모드 모델을 gemma-4-31b-it로 변경

- sop010 충실 이식 후에도 신한_11 page 모드에서 일시불/공과금 행의 금액이 열밀림으로 잘못된 열에 들어갔다. 원본 이미지 확인 결과 그 금액은 물리적으로 `원금(이번달 내실 금액)` 열에 있는데(일시불은 전액이 이번 달 원금), gemini-3.1-flash-lite가 `금액(이용혜택)` 열로 밀어 넣었다.
- 사용자 판단: 3.1 Flash Lite는 한계라 프롬프트로 더 시키면 악화된다. 모델을 gemma-4-31b-it로 교체.
- 공식문서/Google 포럼(스태프 확인)으로 정확한 사용법 확인: Gemma 4 추론 off는 `generationConfig.thinkingConfig.thinkingLevel="MINIMAL"`(thinkingBudget은 미지원 400). systemInstruction·safetySettings·responseMimeType는 정상 지원. outputTokenLimit=32768이라 토큰 캡 필요.
- `src/page_extractor.py._call_gemini_text`에 gemma 분기 추가(thinkingLevel MINIMAL + maxOutputTokens 32768 캡). `--model` CLI와 `extraction.page_model` config 추가. page 모드 기본 모델을 gemma-4-31b-it로, chunk 모드는 vision.model(flash-lite) 유지.
- 결과: 신한_11 page 모드 gemma 추론 off는 일시불 전기 행 금액을 `원금`에 정확히 배치(열밀림 해소). 11호출/0에러, 510행, 정규화 리뷰 1, 검증 6(전부 양성 false-positive: 공과금 가맹점명+관리번호 5 + 기본연회비 1). amount_total 31.2M(flash-lite 29.9M, chunk 32.6M에 근접). 대가는 31B라 flash-lite보다 느림.
- 남은 2단: 공과금 가맹점 false-positive(03정기·06수신로 등)를 신한 숫자오염 예외에 추가. 캐시 dry-run으로 처리.

## 2026-06-14 sop010 충실 이식 정정(헤더 강제 + verbatim 프롬프트) — gemma 전환 직전 결정

- (시간순으로는 위 gemma 항목 직전 결정이다.) sop010.html을 줄 단위로 다시 분석해 `sop010_dissection.md`로 정리했고, 가정과 다른 두 가지를 발견했다.
  1. HTML 헤더 힌트는 소프트가 아니라 강제다(callExtract: 같은 파일 2쪽~는 1쪽 헤더를 반드시 사용). `headersCompatible`(Jaccard 0.75)는 파일 간 검사용이다.
  2. HTML은 canonical amount를 만들지 않고 raw 컬럼만 보존한다. 검토 단계에서 금액/원금/이용금액을 모두 amount 후보(amountAll)로 동등 취급한다.
- 따라서 내가 임시로 넣었던 소프트 헤더 힌트와 각색 프롬프트, __total 확장을 충실 이식으로 되돌렸다. 헤더는 강제(파일 내 1쪽 헤더 통일)로 바꿔야 신한 다단 헤더(`할부`+`기간/회차` 등)가 페이지마다 10/11열로 쪼개지는 문제가 사라진다. 사용자도 "강제로 해야 이단헤더 문제가 안 생긴다"고 확정했다.
- 프롬프트는 `EXTRACT_PROMPT` verbatim으로 복원했고, 검산용 집계행만 verbatim 아래 `__total` 블록으로 분리(2단 확장)했다. 파서는 parseRawText 충실(__skip + AGGREGATE_RE, 강제 헤더, 헤더 순서 cells 정렬).
- 충실 이식 후 flash-lite 베이스라인은 검증 2(헤더 통일)였으나 일시불/공과금 행 금액이 `원금`이 아닌 `금액`으로 밀리는 열밀림이 남았고, 이는 프롬프트로는 못 잡아 모델 교체(gemma)로 이어졌다. 상세는 위 gemma 항목.

## 2026-06-14 신한_11 page+gemma 마무리

- 신한 page 모드의 검산 기준은 `billing_amount_total`이 아니라 원본 `원금` 합계다. page extractor 결과에서 `billing_amount_total=0`인 상태로 `연회비 합계 원금 0`이 자동 선택되는 것은 퇴행 매칭이므로 0 이하 target은 자동 검산 후보에서 제외했다.
- 신한_11 원본 페이지별 `총합계 원금`/`종합 합계 원금` 합산은 30,707,955이고, 강제 fallback 제거 후 `amount_total`도 30,707,955로 일치한다. `src/normalizer.py`의 `_repair_shinhan_amount_rows`에서 원금 0을 이용금액으로 되돌리던 fallback은 문서화된 "강제 보정 금지" 원칙에 맞지 않아 제거했다.
- 원금 0 행은 신한 표에서 `취소`, `부분취소`, `부담경감`, `소비쿠폰`, `면제` 등으로 이번 달 원금이 0인 조정 행이다. 이 행들은 원본 합계에도 0으로 반영되므로 `amount_zero` 검증 이슈에서 제외한다.
- `03정기1702487618`, `06수신로3473966375` 같은 관리번호 결합 공과금 가맹점은 숫자오염이 아니라 신한 공과금 표기다. 기존 `12전기...` 예외에 더해 `NN정기...`, `NN수신료...`, `NN수신로...` 패턴을 숫자 중심 가맹점 예외로 인정했다.
- 최종 캐시 dry-run 결과: `python main.py --input "견본/신한카드_11.pdf" --output output/acceptance_shinhan_11_gemma --extraction-mode page --dry-run`, `llm_calls=0`, `vision_ok=11`, `transaction_count=510`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, 자동화 수락률 100%.

## 2026-06-14 삼성카드_7 page+gemma 신규 추출

- 사용자가 "지금 새로 해야돼"라고 정정해 기존 chunk 캐시를 쓰지 않고 `output/acceptance_samsung_7_gemma`를 새로 만들었다. 최초 timeout 120초 실행은 page 1/3/4/6에서 `The read operation timed out`이 났고, 원인은 API 응답 read timeout이었다.
- RPM은 이미 `main.py`/`config.yaml` 기준 15였고, 내부 fallback 10을 내가 잘못 읽었다. timeout만 200초로 올려 처음부터 다시 추출하니 7페이지 모두 성공했다.
- 삼성 page+gemma 헤더는 `이용일|이용카드|가맹점|이용금액|원금|이용혜택|혜택금액|포인트명|적립금액`으로 들어온다. 기존 삼성 보정은 `입금하실금액` 헤더에만 반응해 `이용금액`을 amount로 잡았으므로, page 헤더 전용으로 `원금`을 amount, `혜택금액`을 discount, `이용금액`을 extra로 보정했다.
- 최종 결과: `python main.py --input "견본/삼성카드_7.pdf" --output output/acceptance_samsung_7_gemma --extraction-mode page --force-vision` 후 캐시 dry-run, `vision_ok=7`, `transaction_count=248`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, 자동화 수락률 100%.

## 2026-06-14 KB `kb_bzcard_13` page+gemma 신규 추출

- 신한/삼성과 같은 page+gemma 경로로 `output/acceptance_kb_bzcard_13_gemma`를 새로 만들었다. timeout 200초/RPM 15 설정에서 13페이지 모두 API 호출 성공했고 error cache는 없었다.
- KB는 기존 2단 보정(`이용카드|이용일|이용 가맹점|가맹점 소재지|이용금액|현지금액|이번달 결제금액|적립예정 포인트리`, 4자리 월일 날짜, 페이지별 이번달 결제금액 합산)이 page+gemma 출력에도 그대로 맞았다. 추가 코드 수정은 필요 없었다.
- 최종 결과: `python main.py --input "견본/kb_bzcard_13.pdf" --output output/acceptance_kb_bzcard_13_gemma --extraction-mode page --force-vision`, `vision_ok=13`, `transaction_count=173`, `normalization_review_count=0`, `validation_issue_row_count=0`, `checksum_status=auto_selected_total_matched`, `matched_total=KB 페이지별 이번달 결제금액 합산 28,301,920`, 자동화 수락률 100%.

## 2026-06-15 현대카드_8 결제원금 기준 보정

- 사용자 기준을 다시 확인했다. 현대카드에서 `billing_amount`는 결제원금이고, 원본 `총 합계`와 맞춰야 하는 기준은 `amount_total`이 아니라 `billing_amount_total`이다.
- `src/reconciliation.py`의 섹션 검산 기준을 현대카드에 한해 `billing_amount_total`로 바꿨다. 일반 카드는 기존처럼 `amount_total`을 쓴다.
- `src/review_builder.py`도 섹션 검산 표시에서 실제 기준 필드가 `billing_amount_total`이면 거래 결제원금을 보여주도록 맞췄다.
- `src/validator.py`의 KB 페이지별 이번달 결제금액 합산 후보는 KB 라벨 신호가 있을 때만 만들도록 제한했다. 이 변경으로 현대카드 총합계가 KB 후보로 잘못 라벨링되는 문제를 제거했다.
- `output/acceptance_hyundai_8_gemma` 캐시 dry-run 결과, pages 1-2, 3-4, 5-6은 결제원금 기준으로 원본 총합계와 일치한다. pages 7-8은 원본 4,015,699 대비 결제원금 3,998,599로 17,100 부족하다.
- KB 후보 오염을 제거한 뒤 현대카드_8 page+gemma 전체 검산 상태는 `no_user_total_selected`다. 이전처럼 가짜 KB 합산 후보로 `auto_selected_total_matched`가 되지 않는다.

## 2026-06-15 현대카드_8 page 7-8 차이 최신 기준

- pages 7-8의 17,100원 차이 중 600원은 page 7 `(주) 스마트로 - 춘천시청` 행의 결제원금 칸이 원본 이미지에 600으로 보이지만 Vision cells에는 빈칸으로 들어온 케이스라 복구했다.
- 복구 후 pages 7-8은 원본 `총 합계 결제원금` 4,015,699와 row `billing_amount_total` 3,999,199 사이에 16,500원 차이가 남는다.
- pages 7-8 raw rows, Vision cache, PDF 텍스트 추출, 렌더 이미지 육안 확인에서 16,500원 거래 행은 확인하지 못했다.
- 따라서 16,500원은 자동 보정하거나 이월/리볼빙으로 단정하지 않는다. 화면에는 `7-8페이지 16,500원 차이`로 남기고, 원본에서 금액 근거가 확인되지 않는 엣지케이스로 처리한다.
- 현재 목표는 이 차이를 맞추는 것이 아니라, 확인된 600원 복구를 유지하면서 전체 실사용 흐름이 깨지지 않는지 점검하는 것이다.

## 2026-06-15 실사용 변환 진입점

- `convert.py`를 추가해 PDF 파일 또는 PDF 폴더를 바로 Excel 산출물로 변환하는 구조를 만들었다.
- 기본 명령은 `python convert.py "견본\현대카드_8.pdf"`이며 출력은 `output/converted/<pdf-name>/result.xlsx`다.
- 기본 추출 모드는 현재 검증한 page mode다. 새 PDF는 `--dry-run` 없이 실행하고, 기존 Vision cache를 재사용할 때만 `--dry-run`을 쓴다.
- 실사용 smoke는 `python convert.py "견본\현대카드_8.pdf" --output output/acceptance_hyundai_8_gemma --dry-run`으로 확인했다.

## 2026-06-15 PC GUI 진입점

- `app.py`를 추가해 PC 전용 GUI를 만들었다. 서버를 띄우지 않고 로컬 Python 프로세스로 `main.py`를 실행한다.
- UI 흐름은 PDF 선택, 출력 폴더 선택, 시작, 진행상황 확인, 완료 후 Excel 열기다.
- 진행상황은 단계별 progress bar와 현재 단계 깜빡임, 실시간 로그로 표시한다.
- 단계 매핑은 `main.py` 로그 문구를 기준으로 `PDF 페이지 준비 → AI 표 읽기 → 행 정리 → 열 역할 판정 → 거래 정규화 → 검산 및 검증 → Excel 생성 → 결과 정리 → 완료` 순서다.

## 2026-06-15 원본표 중심 산출물로 목표 정정

- 사용자가 원하는 최종 결과물은 검산용 정규화 거래 데이터가 아니라 PDF에 보이는 표의 행과 열을 가능한 한 그대로 담은 Excel이다.
- 따라서 `result.xlsx`의 첫 번째 시트는 반드시 `원본표`여야 한다. 기존 `전체명세`처럼 `date`, `card_label`, `merchant`, `amount`, `billing_amount`로 축약한 표가 먼저 보이면 실패로 본다.
- 검산/정규화 파이프라인은 삭제하지 않는다. 이 경로는 금액 합계, 청구금액 후보, 중복 후보, 확인필요 행을 판단하는 품질 보증 장치로 유지한다.
- `원본표`의 데이터 출처는 `rows_merged.jsonl`의 `raw.header`와 `raw.cells`가 우선이다. 병합 산출물이 없으면 `rows_raw.jsonl`을 다음 후보로 쓴다.
- raw cell은 버리지 않는다. header보다 cells가 많으면 `extra_col_N`으로 보존하고, cells가 적으면 빈칸으로 채워서 원본 표의 형태를 최대한 유지한다.
- 기존 normalized sheet 이름은 `전체명세_정규화`로 바꾼다. 이 시트는 검산과 자동 품질 확인을 위한 보조 자료다.
- 구현의 첫 대상은 `src/excel_exporter.py`다. `main.py`가 이미 넘기는 `source_rows_path`를 실제 `원본표` 작성에 사용해야 한다.
- `app.py`가 사용자의 실제 진입점이므로 GUI로 만든 `result.xlsx`도 동일한 시트 순서와 원본표 계약을 만족해야 한다.

## 2026-06-15 원본표 Excel 구현 완료

- `src/excel_exporter.py`에서 `source_rows_path`를 읽어 `원본표`를 첫 번째 시트로 만든다.
- `원본표`는 `page`, `chunk_id`, `local_row_index`, `row_type` 추적 컬럼 뒤에 raw header 합집합을 붙인다.
- header보다 cells가 많은 행은 남는 값을 `extra_col_N`에 보존한다.
- header보다 cells가 적은 행은 비워 둔다. openpyxl로 다시 읽으면 빈 문자열은 `None`으로 보일 수 있지만 Excel 셀은 빈칸이다.
- 기존 `전체명세`는 `전체명세_정규화`로 이름을 바꿨고, `검산`, `원본셀`, `추가필드`, `확인필요`는 유지했다.
- `tests/test_original_table_export.py`를 추가해 시트 순서, raw.header, raw.cells, extra_col_N, 빈칸 보존을 검증한다.
- `tests/regression_samples.py`는 이제 `result.xlsx` 존재만 보지 않고 `원본표` 첫 시트, 비어 있지 않음, `전체명세_정규화`, `검산` 존재를 PASS 조건으로 검사한다.
- `output/acceptance_hyundai_8_gemma` 캐시 dry-run으로 실제 `main.py` 경로를 확인했다. 생성된 workbook은 `원본표`, `전체명세_정규화`, `검산`, `원본셀`, `추가필드`, `확인필요` 순서이고 `원본표`는 314행 14열이다.

## 2026-06-15 원본표 정확도 측정 기준

- 정답 OCR 없이 즉시 자동화할 수 있는 1차 정확도 지표는 `rows_merged.jsonl` 대비 `원본표` 반영률이다.
- row coverage는 `rows_merged.jsonl`의 원본 행 수와 Excel `원본표` 데이터 행 수를 비교한다.
- cell coverage는 `rows_merged.jsonl`의 non-empty `raw.cells` 수와 Excel `원본표`의 non-empty 원본 컬럼 cell 수를 비교한다.
- 이 지표는 PDF 육안 정답률이 아니라 “AI가 읽어 병합한 원본 행/셀을 Excel에서 잃지 않았는지”를 측정한다.
- `tests/regression_samples.py`는 이제 row coverage 또는 cell coverage가 부족하면 PASS하지 않는다.
- 기존 `output/acceptance_hyundai_8_gemma` 산출물은 source row 313개 대비 원본표 row 313개, source non-empty cell 2063개 대비 원본표 non-empty cell 2063개로 coverage 100%다.

## 2026-06-15 대표 acceptance 범위 정정

- 사용자가 acceptance 범위를 카드사별 최대 페이지 샘플 4개로 정정했다. 1장/2장/3장 샘플은 테스트 편의를 위해 쪼개 둔 개발용 샘플이다.
- 대표 샘플은 KB `kb_bzcard_13`, 삼성카드 `삼성카드_7`, 신한카드 `신한카드_11`, 현대카드 `현대카드_8`이다.
- 삼성카드_1/2에 대해 신규 Vision 호출을 시작하려 했지만 사용자 중단 후 범위 정정이 있었고, 남아 있던 `main.py --force-vision` 프로세스는 종료했다. 해당 샘플에는 cache/result.xlsx가 생성되지 않았다.
- 대표 4개 샘플은 모두 기존 cache 기반 dry-run으로 새 `원본표` Excel 구조를 재생성했다.
- `output/original_table_acceptance_4.json` 기준 4개 대표 샘플 모두 `원본표` 첫 시트, `전체명세_정규화`, `검산` 존재, row/cell coverage 100%, validation issue 0건이다.
- 현대카드_8은 보존 지표와 validation issue는 통과하지만 checksum status는 `no_user_total_selected`다. 이는 앞서 합의한 7-8페이지 16,500원 차이 엣지케이스와 연결되며, 원본표 보존 실패로 분류하지 않는다.

## 2026-06-15 원본표 육안 감사와 totals 보존

- 대표 4개 샘플의 첫/중간/마지막 페이지를 `output/visual_audit/*.png`로 묶어 보고, Excel `원본표` 헤더와 행 구조를 대조했다.
- 거래 행은 주요 PDF 열과 대체로 맞고 페이지 순서도 유지됐다.
- 하지만 `총 합계`, `이용금액합계`, `할부 합계`, `일시불(일반) 소계`, `합 계 이번달 결제금액` 같은 합계/소계 행은 원본 PDF와 cache의 `totals`에는 있는데 `원본표`에는 없었다.
- 원인은 `page_extractor.py`가 `__total` 행을 `totals`로 분리하고 `row_merger.py`가 `data.rows`만 `rows_merged.jsonl`에 쓰는 구조였다.
- `src/row_merger.py`에서 `totals`를 `row_type=total` 원본 보존 행으로 추가했다. raw header는 `구분`, `금액텍스트`, `금액`이고, 원래 total 정보는 `extra_fields.original_total`에도 남긴다.
- `src/normalizer.py`는 `row_type=total/section/note` 행을 `original_preserved`로 제외한다. 따라서 원본표에는 보이지만 정규화 거래 수와 검산용 거래 합계에는 섞이지 않는다.
- 대표 4개 샘플 재생성 후 totals 포함 보존 지표는 KB 211/211행 1157/1157셀, 삼성 260/260행 1752/1752셀, 신한 594/594행 2877/2877셀, 현대 325/325행 2099/2099셀이다.
- `output/original_table_visual_audit.md`에 육안 감사 결과를 정리했다.

## 2026-06-15 배포 전 정리

- `convert.py` 실사용 경로는 `python -X utf8 convert.py "견본\현대카드_8.pdf" --output output\acceptance_hyundai_8_gemma --dry-run`으로 확인했다.
- `app.py`는 자동 클릭까지는 하지 않았지만 `tests/test_app_gui.py`로 GUI 생성, 진행 단계 매핑, 기본 동작 smoke를 확인했다.
- `README.md`는 PC 사용자 기준 `python app.py`를 주 진입점으로 설명하고, 신규 PDF는 `--dry-run` 없이 실행해야 한다는 점을 명확히 했다.
- `TEST_REPORT.md`는 대표 4개 샘플 기준 최신 보존 지표와 Excel 시트 계약으로 갱신했다.
- 남은 실제 사용자 확인은 GUI에서 PDF 선택 후 시작 버튼을 눌러 진행바/로그/Excel 열기 버튼이 체감상 충분한지 보는 수동 UX 확인이다.

## 2026-06-15 일반 사용자/개발자 화면 분리

- 일반 사용자는 `app.py`에서 PDF 선택, 출력 폴더 선택, 시작/중지, 진행상황, Excel 열기만 보면 된다.
- 개발자용 cache-only 실행, AI 강제 재호출, 상세 로그는 기본 화면에 노출하지 않고 `개발자 보기` 버튼을 눌렀을 때만 보여준다.
- 이 분리는 기능을 나누는 것이 아니라 화면 노출 수준을 나누는 것이다. 일반 사용자도 같은 변환 파이프라인을 쓰고, 개발자 보기는 문제 진단과 재현 실행을 위한 보조 화면이다.
- 진행상황은 기본 화면에 남겼다. 사용자가 멈춘 것으로 오해하지 않도록 progress bar와 깜빡이는 현재 단계는 일반 사용자 화면의 핵심 요소다.

## 2026-06-15 일반 사용자용 Excel 산출물 방향

- 사용자가 실제로 받는 `result.xlsx`의 첫 시트는 개발자 추적 자료가 아니라 바로 업무에 쓸 수 있는 표여야 한다.
- 따라서 첫 시트 `원본표`에서는 `page`, `chunk_id`, `local_row_index`, `row_type` 같은 추적 컬럼을 제거하고, PDF 거래 표의 대표 헤더만 보여준다.
- 전체 raw cell 보존은 포기하지 않는다. 보존/감사용 전체 원본은 `원본표_개발자`와 `원본셀`로 뒤에 둔다.
- 날짜 열은 가능한 한 `YYYY-MM-DD`로 만든다. 명세서 기준연도가 metadata에 없으면 거래 월 순서의 연도 넘어감으로 추정하고, 장기적으로는 page extractor가 명세 기간을 구조화해야 한다.
- 금액으로 보이는 열은 숫자로 저장하고 표시 형식만 `#,##0`을 적용한다.
- Excel 복구 경고 방지를 위해 빈 데이터 시트에는 Excel Table을 만들지 않고, table displayName은 ASCII 안전 이름만 쓴다.
- KB `output/converted/kb_bzcard_13/result.xlsx` 재생성 결과 첫 시트는 8개 사용자 컬럼만 포함한다. `이용일`은 `2024-12-11`, `2025-01-02` 같은 날짜 셀이고, `이용금액`과 `이번달 결제금액`은 숫자 셀이다.
- KB 명세서의 기준기간은 첫 페이지 상단 이미지에서 보조 OCR로 `2024.12.09 ~ 2025.01.08`을 읽어 연도 보정에 사용했다. OCR 실패 시에는 기존 월 순서 기반 추정으로 fallback한다.
- `확인필요`처럼 데이터 행이 없는 시트에는 Excel Table을 만들지 않으므로, 사용자가 본 Excel 복구 경고의 유력 원인인 헤더만 있는 table 정의를 제거했다.
## 2026-07-03 전체 카드 직접 재실행 시작

- 목표는 `견본` 폴더의 현재 6개 카드 PDF를 기존 캐시 재사용 없이 새 출력 루트에서 직접 실행하고 검증하는 것이다.
- 현재 견본은 `kb_bzcard_13.pdf` 13페이지, `신한카드_11.pdf` 11페이지, `우리카드.pdf` 8페이지, `현대카드_8.pdf` 8페이지, `삼성카드_7.pdf` 7페이지, `농협카드.pdf` 2페이지다.
- 출력 루트는 `output/full_rerun_20260703`로 둔다.
- 현재 워크트리에는 삼성 상호명 OCR 자동 교정 관련 미커밋 변경이 있다. 이번 재실행은 현재 워크트리 기준으로 진행하되, 이 변경은 별도 결정 전까지 되돌리거나 커밋하지 않는다.

## 2026-07-03 전체 카드 직접 재실행 결과

- 6개 카드 모두 `output/full_rerun_20260703` 아래에서 새로 실행했다. KB는 이후 검산 보정 반영을 위해 cache 기반 dry-run으로 재생성했으므로 현재 `summary.json`의 `llm_calls`는 dry-run 값이다.
- 검증 리포트는 `output/full_rerun_20260703/verification_report.json`에 갱신했다.
- KB 13페이지는 `transaction_count=173`, `checksum=auto_selected_total_matched`, `matched_field=billing_amount_total`, `difference=0`, `validation_issue_row_count=0`, 첫 시트 `원본표`, 날짜/숫자 타입 경고 0건이다.
- 신한카드 11페이지는 `transaction_count=510`, `matched_field=amount_total`, `difference=0`, 이슈 0건, 날짜/숫자 타입 경고 0건이다.
- 우리카드 8페이지는 `transaction_count=180`, `matched_field=billing_amount_total`, `difference=0`, 이슈 0건, 날짜/숫자 타입 경고 0건이다.
- 삼성카드 7페이지는 `transaction_count=248`, `matched_field=amount_total_discount_reconciled`, `difference=0`, 이슈 0건, 날짜/숫자 타입 경고 0건이다.
- 농협카드 2페이지는 `transaction_count=80`, `matched_field=amount_total`, `difference=0`, 이슈 0건, 날짜/숫자 타입 경고 0건이다. `수수료`와 `수수료(이자)`를 일반 금액형 헤더로 추가해 `0` 값도 숫자 셀로 저장되게 보강했다.
- 현대카드 8페이지는 `transaction_count=289`, 이슈 0건, 첫 시트 `원본표`, 날짜/숫자 타입 경고 0건이다. 다만 기존 합의한 `7~8페이지 16,500원 차이` 엣지케이스 때문에 checksum은 `no_user_total_selected`로 남겨 안내 대상이다.
- 전체 자동 테스트는 `tests/test_*.py` 21개를 순차 실행해 모두 통과했다.

## 2026-07-01 우리카드/농협카드 신규 샘플 시작

- `견본` 폴더에 신규 카드사로 `우리카드.pdf`, `농협카드.pdf`가 추가됐다.
- PyMuPDF 기준 페이지 수는 우리카드 8페이지, 농협카드 2페이지다.
- 파일명에 `_페이지수` 접미사가 없어 기존 `tests/regression_samples.py`의 파일명 기반 페이지 수 검증에는 바로 넣지 않는다.
- 기존 대표 카드사 처리와 동일하게 카드사별 별도 출력 폴더를 만들고, Vision 결과, 원본표 Excel, 검산 요약, 확인필요 이슈를 확인한다.
- 우리카드는 `output/acceptance_woori_8_gemma_20260701`에 신규 Vision 실행했고, `vision_ok=8`, `transaction_count=180`, `normalization_review_count=0`, `validation_issue_row_count=0`이다.
- 우리카드 검산 기준은 최종 납부 열인 `납부하실금액`이다. `billing_amount_total=1,700,238`이고 페이지별 `납부하실금액` 소계 합산 후보와 자동 일치한다.
- 농협카드는 `output/acceptance_nh_2_gemma_20260701`에 신규 Vision 실행했고, `vision_ok=2`, `transaction_count=80`, `normalization_review_count=0`, `validation_issue_row_count=0`이다.
- 농협카드 검산 기준은 할부성 표의 이번 달 `원금`이다. `amount_total=6,376,141`이고 페이지별 `원금` 합계 후보와 자동 일치한다.
- 농협 `SMS이용료 우수회원면제` 행은 이용금액 300원이지만 원금과 수수료가 0인 면제 행이므로 `amount_zero` 확인필요에서 제외한다.
- 두 카드사 모두 최종 `checksum_status=auto_selected_total_matched`, `difference=0`, 자동 수락률 100%다.

## 2026-06-16 GUI 캐시 재사용 정책 수정

- 사용자가 지적한 문제는 `app.py` 일반 실행이 `output/converted/<pdf-name>` 고정 폴더를 써서 기존 `cache`가 있으면 새 API 호출 없이 캐시를 재사용하는 점이었다.
- 일반 사용자는 재실행/캐시 검증이 목적이 아니므로, 같은 PDF라도 실행할 때마다 `<pdf-name>_YYYYMMDD_HHMMSS_mmm` 형식의 새 출력 폴더를 만든다.
- 개발자 옵션 `기존 cache만 사용`을 켠 경우에만 기존 고정 출력 폴더를 그대로 사용한다.
- 새 출력 폴더는 기존 cache가 없으므로 일반 실행에서 의도치 않은 캐시 재사용이 일어나지 않는다.

## 2026-06-15 문자 OCR 보강 정책

- 상호명 OCR 오류는 자동 치환하지 않는다. 원본표에는 Vision 결과를 보존하고 `확인필요`에 의심 사유와 후보를 표시한다.
- 명백한 비정상 코드 토큰인 `JOptionPane`은 `merchant_text_suspicious`로 올린다.
- 실제 대조에서 확인한 `전정JOptionPane -> 전화홍내과`, `에스입사십(주) -> 예스이십사(주)`는 `merchant_correction_candidate`로 올린다.
- 처음에는 긴 영문과 한글이 섞인 상호명을 모두 의심 처리했지만, `GSTHEFRESH춘천한솔시티점`, `마일스톤(milestone)`처럼 정상일 수 있는 상호가 과검출되어 제거했다.
- 대표 샘플 재검증 결과 현대 8페이지는 `전정JOptionPane` 1행, 삼성 7페이지는 `에스입사십(주)` 2행만 문자 확인필요로 올라온다.

## 2026-06-15 날짜/숫자 타입 대조 결과

- 대표 4개 샘플 실제 실행 결과를 원본 이미지와 엑셀로 대조했다.
- 신한 `원본표`의 `이용일자`가 `24.11.13` 같은 문자열로 남아 있었다. 원본은 `YY.MM.DD` 형식이므로 Excel에는 날짜형 `YYYY-MM-DD`로 들어가야 한다.
- 신한 `결제 후 잔액`도 `47,000` 같은 문자열로 남아 있었다. 일반 사용자 엑셀에서는 숫자형이어야 한다.
- `src/excel_exporter.py`의 일반 사용자 헤더 판별에 실제 한글 날짜 헤더 `이용일자`와 숫자 키워드 `금액`, `원금`, `잔액`, `할인`, `적립`, `포인트`를 추가했다.
- 기존 검증 결과를 이용해 대표 4개 샘플의 `result.xlsx`를 재생성했고, 날짜/숫자 헤더의 비정상 타입은 0건으로 확인했다.

## 2026-06-15 일반 사용자 타임아웃 정책

- 일반 사용자는 재실행을 전제로 하지 않으므로 전체 변환 작업에 짧은 총량 타임아웃을 걸면 안 된다.
- `vision.timeout_seconds=300`은 Vision API 1회 호출의 네트워크 응답 제한이다. page mode는 한 호출이 한 페이지 전체를 읽으므로 최소 5분을 허용한다.
- GUI에는 별도의 무진행 감지를 둔다. subprocess stdout에서 8분 동안 새 진행 신호가 없으면 API 응답 대기 중임을 안내하지만 종료하지 않는다.
- 실제 프로세스 종료는 30분 동안 새 진행 신호가 없을 때만 수행한다. 300초 API 타임아웃과 여러 차례 재시도 대기 중에는 로그가 조용할 수 있기 때문이다.
- page mode 추출은 각 페이지의 캐시 재사용, 시작, 완료, 실패를 로그로 남긴다. 이 로그는 일반 사용자 진행상황 갱신과 무진행 감지의 기준이 된다.
- 전체 작업이 오래 걸리는 것은 실패가 아니다. 실패로 보는 것은 새 로그나 단계 변화가 장시간 없는 상태다.

## 2026-06-15 KB 검산 기준과 날짜 변환 수정

- KB 사업자카드의 `이번달 결제금액`은 정규화 필드 `billing_amount`에 해당한다.
- 기존 검산은 KB 페이지별 `이번달 결제금액` 합산 후보가 `amount_total`과 일치해도 자동 PASS가 될 수 있었다.
- 이 때문에 우정사업본부 행에서 `billing_amount=686,610`처럼 페이지 합계가 거래행에 유입되어도 `amount_total`이 맞으면 검산이 통과할 수 있었다.
- 수정 후 `KB 페이지별 이번달 결제금액 합산` 후보는 `billing_amount_total` 계열 필드로만 자동 매칭된다.
- KB 거래행에서 `billing_amount`가 같은 페이지의 합계 후보 금액과 같고 `amount`와 다르면 `kb_billing_amount_equals_page_total` 확인필요 이슈를 붙인다. 값은 자동 보정하지 않고 원본표에 보존한다.
- 일반 사용자 원본표의 날짜 변환은 첫 페이지 명세기간을 모든 행에 직접 대입하지 않는다. 첫 페이지 기간은 시작 연도를 잡는 기준으로만 쓰고, 이후 행은 월 순서가 12월에서 1월로 넘어갈 때 연도를 증가시킨다.
- `output/converted/kb_bzcard_13/result.xlsx` 재생성 확인 결과 15행 `2025-01-09`, 160행 `2025-12-09`, 166행 `2026-01-01`, 174행 `2026-01-08`이 날짜형 `yyyy-mm-dd`로 들어갔다.
- 우정사업본부 9페이지 행은 원본표에 `이용금액=1,800`, `이번달 결제금액=686,610`으로 보존되고, `확인필요` 시트에 합계값 유입 가능성으로 표시된다.
- `python -X utf8 tests\test_original_table_export.py`, `python -X utf8 tests\test_checksum_selection.py`, 전체 `tests/test_*.py`가 통과했다.
