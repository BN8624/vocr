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
