# STATUS

This status file follows `newplan.md`.

Status values:

```text
DONE
PARTIAL
PLANNED
BROKEN
NEEDS_VERIFICATION
```

| Feature | Status | Evidence | Automation Contribution | Remaining Problem |
|---|---|---|---|---|
| Vision-first PDF/image pipeline | PARTIAL | `main.py`, `src/page_renderer.py`, `src/chunk_builder.py`, `src/vision_extractor.py` | Core extraction path exists | Acceptance metrics with `--with-vision` are not yet complete |
| Local acceptance sample runner | PARTIAL | `tests/regression_samples.py` | Runs local samples and writes report | Must become strict staged acceptance runner with automation metrics |
| Sample manifest | PARTIAL | `tools/build_sample_manifest.py`, `tests/test_sample_manifest.py` | Standardizes issuer/sample discovery | Writes manifest, but canonical `samples/sample_manifest.json` workflow is not adopted yet |
| Vision cache readiness check | DONE | `tools/check_vision_cache.py`, `tests/test_vision_cache_check.py` | Confirms whether one real API run can be reused for cache-only downstream tests | `output/acceptance_hyundai_1` now has 4/4 successful cached Vision JSON files |
| Excel export | PARTIAL | `src/excel_exporter.py`, `result.xlsx` outputs | Produces workbook for converted rows | Must be validated against non-empty sheet criteria for all acceptance samples |
| Raw cell preservation | DONE | `rows_raw.jsonl`, `rows_merged.jsonl`, `원본셀` sheet | Audit trail | Must remain enforced as automation fields are added |
| Duplicate representative selection | PARTIAL | `src/row_merger.py`, duplicate tests | Reduces inflated totals from overlap chunks | Needs new duplicate statuses from `newplan.md` |
| Column mapping profiles | PARTIAL | `src/profile_store.py`, `profile_manager.py`, `profiles/README.md` | Reuses recurring layout mappings | Stable issuer promotion criteria not implemented |
| Validation and column contamination checks | PARTIAL | `src/validator.py`, validation fixture tests | Catches swapped/contaminated columns | Needs row automation status and rates |
| Checksum candidate selection | PARTIAL | `validation_summary.json`, `review_state.json` | Supports checksum verification | Safe automatic total selection not implemented |
| `automation_summary.json` | PLANNED | `newplan.md` P0-6 | Central automation quality metric | File is not generated yet |
| Row automation status | PLANNED | `newplan.md` P1 | Separates auto/warning/light/hard/blocked | `transactions_validated.jsonl` lacks `automation` field |
| Strict parser + auto recovery | PLANNED | `newplan.md` P1 | Lowers hard-review rate | Parser/recovery sequence not implemented |
| Selective 2-pass Vision | PLANNED | `newplan.md` P1 | Repairs risky chunks only | Not implemented |
| `review.html` exception/debug role | PARTIAL | `src/review_builder.py`, `static/review.*` | Shows only judgment-required steps in current UI | Needs automation metrics first screen and hard failure prioritization |
| `review.py` simple entrypoint | DONE | `review.py`, `tests/test_review_entrypoint.py` | Simplifies single-PDF operation | Must remain secondary to acceptance runner |
| Page-mode extraction (sop010 port) | PARTIAL | `src/page_extractor.py`, `prompts/page_extract_jsonl.md`, `sop010_dissection.md`, `tests/test_page_extractor.py` | 1단 범용 거름망: 페이지 1장=1 호출, 헤더명 키 JSON, 강제 헤더, 적응형 전처리, gemma-4-31b-it(추론 off) | 신한_11 2단 튜닝 완료. 타 카드사 범용성 검증 남음 |

## Current P0 Focus

```text
1. Finish 현대카드_8 checksum by reconciling original 결제원금 totals with billing_amount_total.
2. Investigate pages 1-2 deficit 71,240 and pages 7-8 deficit 16,500 from cached Hyundai outputs.
3. Add only evidence-backed normalization/chunk recovery rules, then rerun 현대카드_8 from cache.
4. Re-run focused checksum, profile, validation, and duplicate tests before committing.
```

## 2026-06-14 Handoff

```text
현대카드_8 latest checksum basis is 결제원금.
Original 총 합계 page sum is 34,523,411.
Current checksum.billing_amount_total is 34,435,671.
Remaining deficit is 87,740.
Pages 3-4 and 5-6 match billing_amount_total.
Pages 1-2 are short by 71,240.
Pages 7-8 are short by 16,500.
Do not solve this as a manual total selection UI issue.
Treat it as a Hyundai billing_amount extraction or omission issue.
```

## 2026-06-14 Latest (supersedes above) — page 모드 + gemma 전환

```text
[현대카드_8 검산 — RESOLVED]
- 위 87,740 차이(1-2쪽 71,240 + 7-8쪽 16,500)는 전월 리볼빙 이월분으로 확정됐다.
- 거래 결제원금 합은 정확하고 차이는 거래가 아닌 이월분이다.
- src/validator.py에 리볼빙 검산 규칙 추가: 이월약정 라벨 + 결제원금<=총합계이면
  잉여(이월분)를 무시하고 billing_amount_total_revolving_carryover로 자동 일치.
- dry-run 중복 과추출 버그도 수정(load_cached_vision_results에 _with_required_defaults).
- 현대카드_8 현재: 299행, auto_selected_total_matched(carryover 87,740).

[현재 작업 = page 모드 1단(sop010 충실 이식) + gemma]
- src/page_extractor.py: 페이지 1장=1 호출, 헤더명 키 JSON Lines, 강제 헤더(파일 내 1쪽
  헤더 통일), 적응형 전처리, 동시성2 + RPM 슬라이딩 큐, 캐시 page_NNN.
- 프롬프트는 sop010 EXTRACT_PROMPT verbatim + __total(검산용) 2단 확장. 분석은 sop010_dissection.md.
- page 모드 기본 모델 = gemma-4-31b-it(추론 off: thinkingLevel MINIMAL, 토큰 32768 캡).
  chunk 모드는 gemini-3.1-flash-lite 유지. config: extraction.page_model, CLI: --model.
- 신한_11 page+gemma: 11호출/0에러, 510행, 정규화 리뷰 0, 검증 0, 자동화 수락률 100%.
  검산은 `billing_amount_total=0` 퇴행 매칭을 막고 `페이지별 총합계 원금 합산=30,707,955`와
  `amount_total=30,707,955`를 자동 일치시킨다. flash-lite의 일시불 열밀림(금액→원금)이 gemma로 해소됨.
- 삼성카드_7 page+gemma: timeout 200초/RPM 15로 신규 추출 완료. 7호출/0에러, 248행,
  정규화 리뷰 0, 검증 0, 자동화 수락률 100%. page 헤더(`이용금액/원금/혜택금액`)에서는
  `원금`을 amount로 보정하고 `혜택금액`은 discount로 분리한다.
- KB `kb_bzcard_13` page+gemma: 13호출/0에러, 173행, 정규화 리뷰 0, 검증 0,
  자동화 수락률 100%. `KB 페이지별 이번달 결제금액 합산=28,301,920`이 amount_total과 자동 일치한다.

[다음 시작점 — 전부 캐시 dry-run, API 불필요]
1. 현대 샘플도 gemma page 모드로 1회 추출해 범용성 검증.
2. chunk 모드 100% 샘플 대비 page+gemma 비교 후 기본 모드 전환 판단.
실행: python main.py --input "견본/<카드>.pdf" --output output/<dir> --extraction-mode page [--dry-run|--force-vision]
```

## 2026-06-15 Latest Hyundai Basis Update

```text
현대카드_8 page+gemma 기준을 결제원금으로 보정했다.
section_reconciliation은 현대카드에서 billing_amount_total을 기준으로 비교한다.
캐시 dry-run 결과 pages 1-2, 3-4, 5-6은 원본 총합계와 결제원금 기준 일치한다.
pages 7-8은 원본 4,015,699 대비 billing_amount_total 3,998,599로 17,100 부족하다.
KB 전용 합산 후보 오염을 제거해서 현재 checksum_status는 no_user_total_selected다.
다음 작업은 pages 7-8의 17,100 부족을 원본 이미지 또는 raw cells 증거로 확정하는 것이다.
```

## 2026-06-15 Latest Hyundai Page 7-8 Edge Case

```text
현대카드_8 page+gemma 기준으로 확인된 보정은 page 7 스마트로 - 춘천시청 600원 결제원금 누락뿐이다.
보정 후 pages 7-8은 원본 총 합계 결제원금 4,015,699와 row billing_amount_total 3,999,199 사이에 16,500원 차이가 남는다.
16,500원은 원본 행, raw cells, PDF 텍스트에서 확인되지 않았으므로 자동 보정하거나 리볼빙으로 단정하지 않는다.
현재 처리 방침은 화면에 7-8페이지 16,500원 차이로 안내하고 엣지케이스로 남기는 것이다.
```

## 2026-06-15 Latest Usable Entry Point

```text
실사용 진입점은 convert.py다.
단일 PDF: python convert.py "견본\현대카드_8.pdf"
폴더 일괄: python convert.py "견본"
기본 출력: output/converted/<pdf-name>/result.xlsx
새 PDF는 --dry-run 없이 실행해야 Vision API를 호출한다.
--dry-run은 기존 output cache가 있을 때만 재검증용으로 사용한다.
```
