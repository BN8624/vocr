# vocr

vocr is a local Python tool for converting image-based Korean credit card statement PDFs into audit-friendly Excel files with a Vision LLM.

The project is not OCR-first. The primary path is:

```text
PDF page image
-> overlapping visual chunks
-> Vision LLM JSON rows/cells
-> duplicate-aware row merge
-> profile-based column mapping
-> normalization
-> validation and automation scoring
-> result.xlsx
```

## Current Goal

The goal is no longer "make a page where a person reviews many rows."

The current goal is:

```text
Automatically convert the local staged Korean card statement samples to Excel, starting with the three 1-page samples.
```

The local acceptance PDFs are currently stored in `견본/` and are intentionally ignored by Git. They are the first acceptance set, not casual examples:

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

## Success Criteria

Current stepwise acceptance starts with one single-page sample:

```bash
python tests/regression_samples.py --samples-dir 견본 --issuer 현대카드 --pages 1 --limit 1
```

Primary acceptance command:

```bash
python tests/regression_samples.py --with-vision
```

The dry-run command remains useful for page rendering, chunking, and HTML structure checks:

```bash
python tests/regression_samples.py
```

First real API target:

```text
현대카드_1.pdf
```

The configured Vision model is `gemini-3.1-flash-lite` in `config.yaml`.

Each acceptance sample should produce:

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
all sample PDFs render successfully
all chunks are generated
Vision extraction succeeds for all required chunks
result.xlsx is generated
전체명세, 검산, 원본셀, 추가필드, 확인필요 sheets exist
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

## Simple Run

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

For the first acceptance target, run the real API once on the PC:

```bash
python main.py --input "견본\현대카드_1.pdf" --output output\acceptance_hyundai_1 --force --force-vision
```

That sends the generated chunk images to Gemini once and writes successful responses as:

```text
output/acceptance_hyundai_1/cache/*.vision.json
```

After the API call, check whether every body chunk and total chunk has a successful cache file:

```bash
python tools/check_vision_cache.py --output output\acceptance_hyundai_1 --write-report
```

If it says `Ready for cache-only tests: yes`, downstream work can be repeated without calling the API:

```bash
python main.py --input "견본\현대카드_1.pdf" --output output\acceptance_hyundai_1 --dry-run
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
전체명세
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
