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
