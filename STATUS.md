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
| Local acceptance sample runner | PARTIAL | `tests/regression_samples.py` | Runs local samples and writes report | Must become strict 9-sample acceptance runner with automation metrics |
| Sample manifest | PLANNED | `newplan.md` P0-1/P0-2 | Standardizes issuer/sample discovery | `tools/build_sample_manifest.py` and `samples/sample_manifest.json` not implemented |
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
1. Build sample manifest generation.
2. Strengthen tests/regression_samples.py as the acceptance runner.
3. Generate merged/automation_summary.json per sample.
4. Add row-level automation status and rates.
```
