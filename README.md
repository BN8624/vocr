# vocr

vocr is a local Python tool for converting image-based Korean credit card statement PDFs into Excel files with a Vision LLM.

The project is not OCR-first. The main product is no longer a normalized checksum table. The main product is an Excel workbook whose first sheet restores the visible PDF table as much as possible.

The primary output path is:

```text
PDF page image
-> Vision LLM JSON rows/cells
-> duplicate-aware row merge
-> original table restoration from raw.header/raw.cells
-> result.xlsx
```

The checksum and normalization path still exists, but it is a quality-assurance path:

```text
PDF page image
-> Vision LLM JSON rows/cells
-> duplicate-aware row merge
-> profile-based column mapping
-> normalization
-> validation and automation scoring
-> auxiliary sheets in result.xlsx
```

## Current Goal

The goal is no longer "make a page where a person reviews many rows" or "export only normalized transaction rows."

The current goal is:

```text
Automatically convert the local staged Korean card statement samples to Excel, with the PDF-visible table preserved as the first sheet.
```

The local sample PDFs are currently stored in `견본/` and are intentionally ignored by Git. Some are split-down development samples. The practical acceptance set is the largest-page representative sample for each card company:

```text
kb_bzcard_13.pdf
삼성카드_7.pdf
신한카드_11.pdf
현대카드_8.pdf
```

The remaining local PDFs are useful for staged debugging and regression, but they are not the final acceptance scope by themselves:

```text
삼성카드_1.pdf
삼성카드_2.pdf
삼성카드_5.pdf
삼성카드_7.pdf
신한카드_1.pdf
신한카드_11.pdf
신한카드_3.pdf
현대카드_1.pdf
현대카드_2.pdf
현대카드_8.pdf
```

`review.html` is a debug and exception screen. If a person must inspect every row, the automation has failed.

## Excel Output Contract

`result.xlsx` sheet order must be:

```text
원본표
전체명세_정규화
검산
원본셀
추가필드
확인필요
```

`원본표` is the main user-facing sheet. It must be first and non-empty. It is built from `rows_merged.jsonl` first, then `rows_raw.jsonl` if merged rows are unavailable.

`원본표` uses `raw.header` and `raw.cells` instead of collapsing the data into `date`, `card_label`, `merchant`, `amount`, and `billing_amount`. Tracking columns are prefixed before the visible PDF columns:

```text
page | chunk_id | local_row_index | row_type | <PDF header columns...>
```

No raw cell should be discarded. If a row has more cells than headers, the remaining values are preserved as `extra_col_1`, `extra_col_2`, and so on. If a row has fewer cells than headers, the missing cells are written as blanks.

`전체명세_정규화` is the old normalized `전체명세` sheet under a clearer name. It is kept for checksum, automation quality checks, and exception handling. It is not the main result.

## Success Criteria

Current representative acceptance samples:

```text
KB: kb_bzcard_13.pdf
삼성카드: 삼성카드_7.pdf
신한카드: 신한카드_11.pdf
현대카드: 현대카드_8.pdf
```

Cache-only representative verification:

```bash
python convert.py "견본\현대카드_8.pdf" --output output\acceptance_hyundai_8_gemma --dry-run
```

For a new PDF with no cache, run without `--dry-run`:

```bash
python convert.py "견본\현대카드_8.pdf"
```

The configured page-mode Vision model is `gemma-4-31b-it` in `config.yaml`. The older chunk mode still uses `gemini-3.1-flash-lite`.

Each representative acceptance sample should produce:

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

Passing means more than `result.xlsx` existing. The target is:

```text
PDF pages render successfully
page-mode Vision extraction succeeds or cache is reused
result.xlsx is generated
원본표 sheet exists
원본표 is the first sheet
원본표 is non-empty
원본표 row/cell preservation is 100% against rows_merged.jsonl
합계/소계 rows from Vision totals are preserved as row_type=total
전체명세_정규화, 검산, 원본셀, 추가필드, 확인필요 sheets exist
automation_summary.json exists
blocked samples == 0
blocked rows == 0
average hard_review_rate <= 5%
average manual_review_rate <= 15%
```

## Automation Metrics

The project should classify rows with these statuses:

```text
auto_confirmed
auto_confirmed_with_warning
needs_light_review
needs_hard_review
blocked
```

Target rates:

```text
P0:
  hard_review_rate <= 5%
  manual_review_rate <= 15%

P1:
  hard_review_rate <= 3%
  manual_review_rate <= 10%

Final:
  hard_review_rate <= 1%
  manual_review_rate <= 5%
  silent_error_count == 0
```

`needs_review` is a safety signal, not a product goal. A high review rate means the automation should be improved.

## Review HTML Role

`review.html` should show automation results and failure causes:

```text
sample name and issuer
page count
transaction count
auto acceptance rate
manual review rate
hard review count
blocked count
checksum status
profile application status
Excel status
```

It should hide normal rows by default:

```text
auto_confirmed
auto_confirmed_with_warning
```

It should prioritize:

```text
blocked rows
needs_hard_review rows
checksum mismatch
duplicate conflicts
profile conflicts
amount candidate conflicts
```

## Convert PDFs To Excel

PC desktop app:

```bash
python app.py
```

The app lets you select PDF files, choose an output folder, start conversion, watch the progress bar and blinking current step, then open the generated Excel file. This is the intended PC user entry point.

Normal user flow:

```text
1. Run `python app.py`.
2. Select one or more PDF statements.
3. Keep `기존 cache만 사용` off for a new PDF.
4. Click `시작`.
5. Open the generated `result.xlsx`.
6. Check the first sheet, `원본표`.
```

For normal use, run `convert.py`. It creates one output folder per PDF and writes `result.xlsx`.

Single PDF:

```bash
python convert.py "견본\현대카드_8.pdf"
```

Folder of PDFs:

```bash
python convert.py "견본"
```

Default outputs:

```text
output/converted/<pdf-name>/
  result.xlsx
  review.html
  summary.json
  merged/
```

Useful options:

```bash
python convert.py "견본\현대카드_8.pdf" --output output/my_statement
python convert.py "견본" --output-root output/batch_run --continue-on-error
python convert.py "견본\현대카드_8.pdf" --dry-run
python convert.py "견본\현대카드_8.pdf" --force-vision
```

`--dry-run` reuses existing Vision cache and does not call the external API. For a new PDF, omit `--dry-run` and make sure `GEMINI_API_KEY` is set in `.env` or the environment.

`review.py` is for converting one PDF and starting the local review server after conversion.

For one PDF:

```bash
python review.py "견본\삼성카드_1.pdf"
```

This converts the PDF, prints the PC link, prints the iPhone/Tailscale link when detected, prints the Excel path, and starts the review server on port `8012` if the port is free.

Convert without starting the server:

```bash
python review.py "견본\삼성카드_1.pdf" --no-server
```

Lower-level command:

```bash
python main.py --input "견본\삼성카드_1.pdf" --output output/samsung_1
```

Dry-run without external Vision calls:

```bash
python main.py --input "견본\삼성카드_1.pdf" --output output/samsung_1 --dry-run
```

## One API Call, Then Cache-Only Testing

For a new sample, run the real API once on the PC:

```bash
python main.py --input "견본\현대카드_8.pdf" --output output\acceptance_hyundai_8_gemma --extraction-mode page --force-vision
```

That sends the generated chunk images to Gemini once and writes successful responses as:

```text
output/acceptance_hyundai_8_gemma/cache/*.vision.json
```

After the API call, check whether every body chunk and total chunk has a successful cache file:

```bash
python tools/check_vision_cache.py --output output\acceptance_hyundai_8_gemma --write-report
```

If it says `Ready for cache-only tests: yes`, downstream work can be repeated without calling the API:

```bash
python main.py --input "견본\현대카드_8.pdf" --output output\acceptance_hyundai_8_gemma --extraction-mode page --dry-run
```

If the cache checker reports `.vision.error.json` files, the previous API attempt failed for those chunks and the real API command must be run again.

## Review Server

For iPhone/Tailscale review:

```bash
python serve_review.py --host 0.0.0.0 --port 8012
```

Example URLs:

```text
PC:     http://127.0.0.1:8012/output/samsung_1/review.html
iPhone: http://<tailscale-ip>:8012/output/samsung_1/review.html
```

Do not use router port forwarding. Use the local machine or Tailscale only, and stop the server after work.

## Profiles

Profiles should become automation inputs, not repeated manual-review artifacts.

A stable issuer profile should eventually include:

```text
issuer
layout_signature
header_signature
column_roles
value_patterns
verified_samples
last_verified_metrics
```

A profile should be promoted to stable only after the issuer's single-page, three-page, and multi-page samples pass with:

```text
blocked rows == 0
hard_review_rate <= 3%
manual_review_rate <= 10%
silent_error_count == 0
```

## Generated Outputs

Main output shape:

```text
output/<sample_name>/
  pages/
  chunks/
  total_chunks/
  cache/
  merged/
    rows_raw.jsonl
    rows_merged.jsonl
    merge_summary.json
    mapping_suggestions.json
    transactions.jsonl
    transactions_validated.jsonl
    validation_summary.json
    validation_issues.json
    automation_summary.json
  review.html
  result.xlsx
  summary.json
```

Excel sheets:

```text
원본표
전체명세_정규화
검산
원본셀
추가필드
확인필요
```

## Current P0 Work

The immediate work order is defined in `newplan.md`.

Priority:

```text
1. add sample manifest generation
2. strengthen tests/regression_samples.py into the acceptance runner
3. generate merged/automation_summary.json
4. add row_status / confidence_score / risk_level
5. add stable profile promotion criteria
6. auto-select checksum candidates when safe
7. refine duplicate statuses
8. add strict parsers and automatic recovery
9. add selective 2-pass Vision
10. keep review.html as an exception/debug screen
11. maintain STATUS.md and TEST_REPORT.md
```

Current manifest command:

```bash
python tools/build_sample_manifest.py --samples 견본 --output output/sample_manifest_current.json
```

## Do Not Do

```text
do not return to OCR-first extraction
do not solve this by hard-coding full card-company parsers
do not treat result.xlsx creation alone as success
do not leave checksum selection as a repeated manual task
do not make users review every row
do not hide uncertain rows silently
do not improve prompts without measuring acceptance metrics
```
